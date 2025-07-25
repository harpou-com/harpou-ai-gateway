"""
title: Example Filter
author: harpou-ai-gateway
author_url: https://github.com/harpou-com/harpou-ai-gateway
funding_url: https://github.com/harpou-com/harpou-ai-gateway
version: 0.1
"""
# 1. Imports
import httpx
import json
import logging
import asyncio
import time
import uuid
from typing import List, Generator, Optional
from pydantic import BaseModel, Field, SecretStr

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# 4. Polling Constants & Helper Function
POLLING_INTERVAL = 2  # secondes
POLLING_TIMEOUT = 300 # 5 minutes

async def poll_task_status(
    client: httpx.AsyncClient, task_id: str, headers: dict
    , pipe_yield_callback: callable) -> dict:
    """
    Sonde le statut d'une tâche asynchrone sur le Gateway.
    Inclut une gestion des timeouts et des tentatives.
    """
    start_time = time.time()
    log.info(f"[{task_id}] Démarrage du polling pour le statut de la tâche.")

    iteration_count = 0
    while time.time() - start_time < POLLING_TIMEOUT:
        try:
            status_url = f"/v1/tasks/status/{task_id}"
            response = await client.get(status_url, headers=headers, timeout=10)
            response.raise_for_status()  # Lève une exception pour les statuts 4xx/5xx

            data = response.json()
            status = data.get("status")
            log.info(f"[{task_id}] Statut de la tâche reçu : {status}")
            
            iteration_count += 1
            if status == "in_progress" and iteration_count % 5 == 0:
                elapsed_time = int(time.time() - start_time)
                status_message = {
                    "content": f"⏳ Tâche en cours... (Statut: {status}, Temps écoulé: {elapsed_time}s)"
                }
                # Utiliser le callback pour "yield" le message à la méthode pipe()
                sse_message = f'data: {json.dumps(status_message)}\n\n'
                await pipe_yield_callback(sse_message)
                log.info(f"[{task_id}] Envoi d'une mise à jour de statut intermédiaire: {status_message}")


            if status in ["completed", "failed"]:
                return data
            # Si le statut est "in_progress", la boucle continue après la pause.
        except httpx.RequestError as e:
            log.warning(f"[{task_id}] Erreur réseau lors du polling : {e}. Nouvelle tentative...")

        await asyncio.sleep(POLLING_INTERVAL)

    log.warning(f"[{task_id}] Le polling a expiré après {POLLING_TIMEOUT} secondes.")
    return {"status": "failed", "error": "Le polling a expiré (timeout)."}

# 5. Main Pipe Class
class Pipe:
    # 2. Valves Class for Configuration (Nested inside Pipe)
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
        GATEWAY_API_KEY: SecretStr = Field(
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
        # Le client est initialisé sans en-têtes spécifiques à une requête
        self.client = httpx.AsyncClient(
            base_url=self.valves.GATEWAY_URL
        )
        log.info(f"HARPOU AI Gateway Pipe initialized for URL: {self.valves.GATEWAY_URL}")

    async def pipes(self) -> List[str]:
        """
        Returns a list of "models" that this pipe can handle.
        These are identifiers that will appear in the Open WebUI model list.
        """
        prefix = self.valves.AGENT_MODEL_PREFIX
        # Example agent models we might want to expose
        agent_models = [
            "deep-research",
            "image-generation",
        ]
        return [f"{prefix}{model}" for model in agent_models]

    async def pipe(
        self, body: dict, __user__: dict
    ) -> Generator[str, None, None]:
        """
        Main entry point for the pipe. It receives a request from Open WebUI,
        forwards it to the HARPOU AI Gateway to start an agentic task,
        and streams back an initial confirmation message.
        """
        log.info(f"Pipe received a request for model: {body.get('model')}")

        try:
            model = body.get("model", "")
            messages = body.get("messages", [])

            if not model.startswith(self.valves.AGENT_MODEL_PREFIX):
                log.warning(f"Model '{model}' is not an agentic model. This pipe will not handle it.")
                yield "data: [DONE]\n\n"
                return

            # Extract the user's question from the last message for logging
            user_question = ""
            if messages and isinstance(messages[-1], dict):
                user_question = messages[-1].get("content", "")

            log.info(f"User question for agent: '{user_question[:100]}...'")

            # Prepare the payload for the gateway
            gateway_payload = {
                "model": model,
                "messages": messages,
            }

            # Préparer les en-têtes pour la requête, y compris la clé API et le SID
            headers = {"Content-Type": "application/json"}
            api_key = self.valves.GATEWAY_API_KEY.get_secret_value()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            # Ajout crucial du SID pour les requêtes agentiques
            sid = __user__.get("sid")
            if sid:
                headers["X-SID"] = sid
                log.info(f"Adding X-SID header for agentic request: {sid}")

            log.info(f"Sending agentic task request to HARPOU AI Gateway for model {model}.")

            # 5. Call the HARPOU AI Gateway
            response = await self.client.post(
                "/v1/chat/completions", json=gateway_payload, headers=headers, timeout=60
            )

            if response.status_code == 202:
                task_id = response.json().get("id")
                if not task_id:
                    log.error("Le Gateway a accepté la tâche mais n'a pas retourné de task_id.")
                    yield 'data: {"error": "La tâche a été acceptée mais aucun ID n\'a été reçu."}\n\n'
                    yield "data: [DONE]\n\n"
                    return

                log.info(f"Agentic task started successfully with task_id: {task_id}")
                yield 'data: {"content": "⏳ Tâche agentique lancée. En attente du résultat..."}\n\n'

                # Démarrer le polling
                task_result = await poll_task_status(self.client, task_id, headers, 
                                                    pipe_yield_callback=lambda msg: self.yield_message(msg, yield_))

                # Traiter le résultat du polling
                if task_result and task_result.get("status") == "completed":
                    final_result = task_result.get("result", "Tâche terminée, mais aucun résultat retourné.")
                    log.info(f"[{task_id}] Tâche terminée avec succès. Envoi du résultat.")
                    yield f'data: {json.dumps({"content": str(final_result)})}\n\n'
                else: # Gère 'failed' et autres statuts d'erreur du polling
                    error_message = task_result.get("error", "Une erreur inconnue est survenue pendant la tâche.")
                    log.error(f"[{task_id}] La tâche a échoué ou a expiré. Erreur: {error_message}")
                    yield f'data: {json.dumps({"error": str(error_message)})}\n\n'

            else:
                log.error(f"Failed to start agentic task. Status code: {response.status_code}, Response: {response.text}")
                yield f'data: {{"error": "Erreur lors du lancement de la tâche. Statut: {response.status_code}"}}\n\n'

        except httpx.TimeoutException as e:
            log.error(f"Timeout error while calling HARPOU AI Gateway: {e}")
            yield 'data: {"error": "Erreur de timeout en contactant le Gateway."}\n\n'
        except Exception as e:
            log.error(f"An unexpected error occurred: {e}", exc_info=True)
            yield 'data: {"error": "Une erreur inattendue est survenue."}\n\n'

        yield "data: [DONE]\n\n"

    async def yield_message(self, message: str, yield_) -> None:
        """
        Wrapper pour la fonction yield_ pour permettre le logging.
        """
        await yield_(message)

            