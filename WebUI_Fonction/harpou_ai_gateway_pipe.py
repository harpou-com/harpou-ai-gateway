"""
title: HARPOU AI Gateway Pipe
author: harpou-ai-gateway
author_url: https://github.com/harpou-com/harpou-ai-gateway
funding_url: https://github.com/harpou-com/harpou-ai-gateway
version: 0.3
"""
# 1. Imports
import httpx
import json
import logging
import asyncio
import uuid
import re
import time
from typing import List, Generator, Optional, Dict
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# 2. Constants
POLLING_INTERVAL = 2  # secondes
POLLING_TIMEOUT = 300 # 5 minutes

def format_sse_chunk(content: str, model: str) -> str:
    """
    Formats a string content into an OpenAI-compatible SSE chunk.
    This ensures that the UI correctly interprets the data as a message part.
    """
    chunk_data = {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": content},
            "finish_reason": None,
        }],
    }
    return f"data: {json.dumps(chunk_data)}\n\n"

def format_sse_info(message: str) -> str:
    """
    Formats a string message into an SSE chunk for an info notification in Open WebUI.
    """
    return f"data: {json.dumps({'info': message})}\n\n"


# 3. Main Pipe Class
class Pipe:
    # Nested Valves Class for Configuration
    class Valves(BaseModel):
        """
        Configuration valves for the HARPOU AI Gateway Pipe.
        These can be set in Open WebUI's settings.
        """
        GATEWAY_URL: str = Field(
            default="http://ai-gateway-dev:5000",
            description="URL of our HARPOU AI Gateway."
        )
        AGENT_MODEL_PREFIX: str = Field(
            default="harpou-agent/",
            description="Prefix for agentic models to be handled by the gateway."
        )
        AGENT_MODEL_NAME_PREFIX: str = Field(
            default="Harpou AI Gateway - ",
            description="Prefix for the display name of agentic models in the UI."
        )
        GATEWAY_API_KEY: str = Field(
            default="",
            description="API Key for authenticating with the HARPOU AI Gateway."
        )

    valves: "Valves"
    client: httpx.AsyncClient

    def __init__(self):
        """
        Initializes the pipe, setting up the configuration and the HTTP client.
        """
        self.valves = self.Valves()
        # Le client est initialisé sans base_url pour permettre la modification dynamique via les valves.
        self.client = httpx.AsyncClient()
        log.info(f"HARPOU AI Gateway Pipe initialized.")

    # --- Helper Methods for Readability and DRY Principle ---

    def _get_base_url(self) -> Optional[str]:
        """Safely gets and validates the gateway URL from valves."""
        gateway_url = self.valves.GATEWAY_URL
        if not gateway_url or not gateway_url.startswith(('http://', 'https://')):
            log.warning(f"Gateway URL is invalid or not yet loaded: '{gateway_url}'.")
            return None
        return gateway_url.rstrip('/')

    def _get_auth_headers(self) -> dict:
        """Constructs the authorization headers."""
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if api_key := self.valves.GATEWAY_API_KEY:
            headers["Authorization"] = f"Bearer {api_key}"
        return headers

    def _clean_model_id(self, raw_model_id: str) -> str:
        """Removes the function-specific prefix added by Open WebUI."""
        # The prefix is typically "<function_id>."
        # We find the first dot and take the rest of the string.
        # This is more robust than hardcoding "harpou_ai_gateway."
        parts = raw_model_id.split('.', 1)
        if len(parts) > 1:
            return parts[1]
        return raw_model_id

    async def pipes(self) -> List[Dict[str, str]]:
        """
        Découverte dynamique des modèles exposés par le Gateway.
        Retourne une liste de dictionnaires {"id": ..., "name": ...} pour Open WebUI.
        """
        try:
            gateway_url = self._get_base_url()
            if not gateway_url:
                return []

            headers = self._get_auth_headers()
            full_url = f"{gateway_url}/v1/models"
            log.info(f"Contacting gateway for models at: {full_url}")

            response = await self.client.get(full_url, headers=headers, timeout=10)
            response.raise_for_status()
            models_data = response.json()
            # La réponse de l'API est {"object": "list", "data": [...]}
            models_list = models_data.get("data", [])

            # 1. Créer la liste des modèles réels (pour le proxy direct)
            real_models = [
                {"id": model["id"], "name": model.get("name", model["id"])}
                for model in models_list
                if isinstance(model, dict) and "id" in model
            ]

            # 2. Créer une version "agent" virtuelle pour chaque modèle réel
            agent_models = [
                {
                    "id": f"{self.valves.AGENT_MODEL_PREFIX}{model['id']}",
                    "name": f"{self.valves.AGENT_MODEL_NAME_PREFIX}{model['name']}" # Nom affiché dans l'UI
                }
                for model in real_models
            ]

            # 3. Retourner uniquement les modèles agents, comme demandé.
            log.info(f"Exposing {len(agent_models)} agentic models to Open WebUI.")
            return agent_models

        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            log.error(f"Erreur réseau ou HTTP lors de la découverte des modèles: {e}")
            return []
        except Exception as e:
            log.error(f"Erreur inattendue lors de la découverte des modèles: {e}", exc_info=True)
            return []

    async def poll_task_status(self, client: httpx.AsyncClient, task_id: str, headers: dict) -> dict:
        """
        Sonde l'endpoint de statut de la tâche du gateway jusqu'à ce que la tâche soit
        terminée, échouée, ou que le timeout soit atteint.
        """
        start_time = time.time()
        gateway_url = self._get_base_url()
        if not gateway_url:
            raise ValueError("Gateway URL is not configured for polling.")

        while time.time() - start_time < POLLING_TIMEOUT:
            try:
                full_url = f"{gateway_url}/v1/tasks/status/{task_id}"
                status_response = await client.get(
                    full_url, headers=headers, timeout=10
                )
                status_response.raise_for_status()
                data = status_response.json()
                status = data.get("status")

                if status in ["completed", "failed"]:
                    return data
                elif status == "in_progress":
                    log.debug(f"[{task_id}] Tâche toujours en cours...")
                else:
                    log.warning(f"[{task_id}] Statut inattendu reçu: {status}")

            except httpx.RequestError as e:
                log.warning(f"[{task_id}] Erreur réseau lors du polling : {e}. Nouvelle tentative...")
            await asyncio.sleep(POLLING_INTERVAL)
        
        raise TimeoutError(f"Le polling pour la tâche {task_id} a expiré après {POLLING_TIMEOUT} secondes.")

    async def _handle_agentic_request(self, body: dict, __user__: dict) -> Generator[str, None, None]:
        """Handles the agentic workflow (task creation and polling)."""
        agentic_start_time = time.time()
        log.info(f"Starting agentic task flow for model: {body.get('model')}")
        gateway_url = self._get_base_url()
        if not gateway_url:
            yield 'data: {"error": "Gateway URL is not configured."}\n\n'
            return

        # Nettoyer l'historique des messages avant de l'envoyer au gateway.
        # Cela empêche le LLM de voir nos préfixes formatés et de les répéter.
        messages_to_send = body.get("messages", [])
        # Le pattern identifie toute ligne commençant par "Réponse de l'agent", avec ou sans formatage.
        # Il gère les deux types d'apostrophes (' et ’) et est flexible sur le formatage.
        # ^\s*                  -> Début de ligne, avec espaces optionnels.
        # (?:.*?)               -> N'importe quel caractère non-gourmand (pour gérer les **)
        # Réponse de l[’']agent -> Le texte clé avec les deux apostrophes.
        # .*                    -> Le reste de la ligne.
        prefix_pattern = re.compile(r"^\s*(?:.*?)Réponse de l[’']agent.*\n?", re.IGNORECASE | re.MULTILINE)

        for message in messages_to_send:
            if message.get("role") == "assistant" and "content" in message and message["content"]:
                content = message["content"]
                # Boucle de nettoyage robuste pour supprimer tous les préfixes accumulés.
                # Cette méthode est plus fiable que re.sub pour les suppressions en début de chaîne.
                while True:
                    stripped_content = content.lstrip()
                    match = prefix_pattern.match(stripped_content)
                    if match:
                        # Si un préfixe est trouvé, le nouveau contenu est tout ce qui se trouve après.
                        content = stripped_content[match.end():]
                    else:
                        break  # Aucun préfixe trouvé, le nettoyage est terminé.
                message["content"] = content

        gateway_payload = {"model": body.get("model"), "messages": messages_to_send}
        # Log de débogage pour vérifier que le payload envoyé est bien nettoyé.
        log.info(f"Sending cleaned payload to gateway: {json.dumps(gateway_payload, indent=2)}")

        headers = self._get_auth_headers()

        # Rendre le SID plus robuste : utiliser celui de l'utilisateur s'il existe, sinon en générer un.
        # C'est crucial car le gateway a besoin d'un SID pour les requêtes agentiques.
        sid = __user__.get("sid")
        if not sid:
            sid = f"pipe-generated-{uuid.uuid4()}"
            log.warning(f"No SID from __user__, generated a temporary one: {sid}")
        
        headers["X-SID"] = sid

        full_url = f"{gateway_url}/v1/chat/completions"
        response = await self.client.post(full_url, json=gateway_payload, headers=headers, timeout=60)

        if response.status_code == 202:
            response_data = response.json()
            task_id = response_data.get("id")
            if not task_id:
                log.error("Gateway accepted the task but did not return a task_id.")
                yield 'data: {"error": "Task was accepted but no ID was received."}\n\n'
                return

            log.info(f"Agentic task started successfully with task_id: {task_id}")
            # Envoyer une notification temporaire à l'UI pour informer l'utilisateur.
            yield format_sse_info("⏳ Tâche agentique lancée. En attente du résultat...")
            # On ajoute une minuscule pause pour s'assurer que la notification a le temps d'être envoyée et affichée
            # avant que le polling potentiellement long ne commence.
            await asyncio.sleep(0.01)

            try:
                task_result = await self.poll_task_status(self.client, task_id, headers)
                if task_result.get("status") == "completed":
                    duration = time.time() - agentic_start_time
                    result = task_result.get("result", "Task completed, but no result returned.")
                    log.info(f"[{task_id}] Task completed in {duration:.2f}s. Result: {result}")

                    if result and isinstance(result, str):
                        # Nettoyer un éventuel préfixe ajouté par le backend pour éviter les doublons.
                        # Même avec le nettoyage du contexte, le LLM pourrait encore générer un préfixe simple.
                        # Cette étape reste une sécurité.
                        cleaned_result = result.lstrip()
                        # On applique la même logique de nettoyage robuste à la réponse finale.
                        while True:
                            match = prefix_pattern.match(cleaned_result)
                            if match:
                                # Si un préfixe est trouvé, on ne garde que ce qui vient après.
                                cleaned_result = cleaned_result[match.end():].lstrip()
                            else:
                                break # Nettoyage terminé.

                        # Déterminer un indicateur visuel (emoji) car le HTML n'est pas rendu correctement.
                        if duration < 15:
                            time_emoji = "⚡️"  # Rapide
                        elif duration < 30:
                            time_emoji = "🐢"  # Moyen
                        else:
                            time_emoji = "🐌"  # Lent

                        # Créer le préfixe formaté avec l'emoji et le temps entre backticks pour un style de code.
                        # C'est une méthode robuste et compatible avec le rendu Markdown de WebUI.
                        time_display = f"`({duration:.2f}s{time_emoji})`"
                        prefix = f"**Réponse de l'agent:** {time_display}\n\n"
                        final_response = f"{prefix}{cleaned_result}"
                        yield format_sse_chunk(final_response, body.get("model"))
                    else:
                        yield format_sse_chunk(str(result), body.get("model"))
                else:  # status == "failed"
                    error_message = task_result.get("error", "An unknown error occurred during the task.")
                    log.error(f"[{task_id}] Task failed: {error_message}")
                    yield format_sse_chunk(f"Error: {error_message}", body.get("model"))
            except TimeoutError as e:
                log.error(f"[{task_id}] Polling timed out: {e}")
                yield format_sse_chunk("Error: The task has timed out.", body.get("model"))
        else:
            log.error(f"Failed to start agentic task. Status: {response.status_code}, Response: {response.text}")
            yield format_sse_chunk(f"Error starting task. Status: {response.status_code}", body.get("model"))

    async def _handle_proxy_request(self, body: dict) -> Generator[str, None, None]:
        """Handles the non-agentic (proxy/streaming) workflow."""
        log.info(f"Proxying non-agentic request for model: {body.get('model')}")
        gateway_url = self._get_base_url()
        if not gateway_url:
            yield 'data: {"error": "Gateway URL is not configured."}\n\n'
            return

        headers = self._get_auth_headers()
        full_url = f"{gateway_url}/v1/chat/completions"

        if body.get("stream", False):
            async with self.client.stream("POST", full_url, json=body, headers=headers, timeout=300.0) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk.decode("utf-8")
        else:
            response = await self.client.post(full_url, json=body, headers=headers, timeout=300.0)
            response.raise_for_status()
            yield f'data: {response.text}\n\n'

    async def pipe(self, body: dict, __user__: dict) -> Generator[str, None, None]:
        """Main entry point for the pipe, routing to the correct handler."""
        raw_model_id = body.get("model", "")
        log.info(f"Pipe received a request for raw model: {raw_model_id}")

        try:
            # Nettoyer l'ID du modèle pour retirer le préfixe de la fonction ajouté par OpenWebUI
            cleaned_model_id = self._clean_model_id(raw_model_id)
            log.info(f"Cleaned model ID: {cleaned_model_id}")

            # IMPORTANT: Mettre à jour le corps de la requête avec l'ID nettoyé pour le transfert
            body['model'] = cleaned_model_id

            # Puisque nous n'exposons que des modèles agents, cette condition devrait toujours être vraie.
            # Nous la gardons pour la robustesse.
            if cleaned_model_id.startswith(self.valves.AGENT_MODEL_PREFIX):
                async for chunk in self._handle_agentic_request(body, __user__):
                    yield chunk
            else:
                # Ce bloc n'est techniquement plus atteignable mais est conservé par sécurité.
                log.warning(f"Requête reçue pour un modèle non-agent '{cleaned_model_id}', qui ne devrait pas être listé. Proxying quand même.")
                async for chunk in self._handle_proxy_request(body):
                    yield chunk

        except httpx.TimeoutException as e:
            log.error(f"Timeout error while calling HARPOU AI Gateway: {e}")
            yield 'data: {"error": "Erreur de timeout en contactant le Gateway."}\n\n'
        except httpx.HTTPStatusError as e:
            log.error(f"HTTP error {e.response.status_code} in proxy: {e.response.text}")
            yield f'data: {json.dumps({"error": f"Request failed with status {e.response.status_code}", "details": e.response.text})}\n\n'
        except Exception as e:
            log.error(f"An unexpected error occurred: {e}", exc_info=True)
            yield 'data: {"error": "Une erreur inattendue est survenue dans le pipe."}\n\n'
        finally:
            # Send a final chunk with a finish_reason to properly terminate the stream
            final_chunk = {
                "id": f"chatcmpl-{uuid.uuid4()}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.get("model", "unknown-model"),
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            yield "data: [DONE]\n\n"
