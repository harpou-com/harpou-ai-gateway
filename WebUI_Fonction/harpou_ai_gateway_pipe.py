"""
title: HARPOU AI Gateway Pipe
author: harpou-ai-gateway
author_url: https://github.com/harpou-com/harpou-ai-gateway
funding_url: https://github.com/harpou-com/harpou-ai-gateway
version: 0.2
"""
# 1. Imports
import httpx
import json
import logging
import asyncio
import time
from typing import List, Generator, Optional, Dict
from pydantic import BaseModel, Field, SecretStr

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# 2. Constants
POLLING_INTERVAL = 2  # secondes
POLLING_TIMEOUT = 300 # 5 minutes

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

    async def pipes(self) -> List[Dict[str, str]]:
        """
        Returns a list of "models" that this pipe can handle.
        These are identifiers that will appear in the Open WebUI model list.
        The format MUST be a list of dictionaries, each with an "id" key.
        """
        prefix = self.valves.AGENT_MODEL_PREFIX
        # Example agent models we might want to expose
        agent_models = [
            "deep-research",
            "image-generation",
        ]
        # Open WebUI expects a list of dictionaries with an 'id' key.
        # The traceback indicates it also requires a 'name' key.
        return [
            {"id": f"{prefix}{model}", "name": f"{prefix}{model}"}
            for model in agent_models
        ]

    async def pipe(
        self, body: dict, __user__: dict
    ) -> Generator[str, None, None]:
        """
        Main entry point for the pipe. It receives a request from Open WebUI,
        forwards it to the HARPOU AI Gateway to start an asynchronous agentic task,
        and then polls for the result, streaming updates back to the client.
        """
        log.info(f"Pipe received a request for model: {body.get('model')}")
        task_id = None

        try:
            model = body.get("model", "")
            messages = body.get("messages", [])

            if not model.startswith(self.valves.AGENT_MODEL_PREFIX):
                log.warning(f"Model '{model}' is not an agentic model. This pipe will not handle it.")

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

            # 6. Handle the gateway's response
            if response.status_code == 202: # 202 Accepted
                response_data = response.json()
                task_id = response_data.get("id")
                if not task_id:
                    log.error("Le Gateway a accepté la tâche mais n'a pas retourné de task_id.")
                    yield 'data: {"error": "La tâche a été acceptée mais aucun ID n\'a été reçu."}\n\n'
                    yield "data: [DONE]\n\n"
                    return

                log.info(f"Agentic task started successfully with task_id: {task_id}")
                yield 'data: {"content": "⏳ Tâche agentique lancée. En attente du résultat..."}\n\n'

                # 7. Poll for the task result
                start_time = time.time()
                while time.time() - start_time < POLLING_TIMEOUT:
                    try:
                        status_response = await self.client.get(
                            f"/v1/tasks/status/{task_id}", headers=headers, timeout=10
                        )
                        status_response.raise_for_status()
                        data = status_response.json()
                        status = data.get("status")

                        if status == "completed":
                            result = data.get("result", "Tâche terminée, mais aucun résultat retourné.")
                            log.info(f"[{task_id}] Tâche terminée. Résultat: {result}")
                            yield f'data: {json.dumps({"content": str(result)})}\n\n'
                            break  # Sortir de la boucle de polling
                        elif status == "failed":
                            error_message = data.get("error", "Une erreur inconnue est survenue pendant la tâche.")
                            log.error(f"[{task_id}] La tâche a échoué: {error_message}")
                            yield f'data: {json.dumps({"error": str(error_message)})}\n\n'
                            break # Sortir de la boucle de polling
                        elif status == "in_progress":
                            log.debug(f"[{task_id}] Tâche toujours en cours...")
                        else:
                            log.warning(f"[{task_id}] Statut inattendu reçu: {status}")

                    except httpx.RequestError as e:
                        log.warning(f"[{task_id}] Erreur réseau lors du polling : {e}. Nouvelle tentative...")
                    await asyncio.sleep(POLLING_INTERVAL)
                else: # S'exécute si la boucle while se termine sans 'break' (timeout)
                    log.warning(f"[{task_id}] Le polling a expiré après {POLLING_TIMEOUT} secondes.")
                    yield 'data: {"error": "La tâche a expiré (timeout)."}\n\n'

            else:
                log.error(f"Failed to start agentic task. Status code: {response.status_code}, Response: {response.text}")
                yield f'data: {json.dumps({"error": f"Erreur lors du lancement de la tâche. Statut: {response.status_code}"})}\n\n'

        except httpx.TimeoutException as e:
            log.error(f"Timeout error while calling HARPOU AI Gateway: {e}")
            yield 'data: {"error": "Erreur de timeout en contactant le Gateway."}\n\n'
        except Exception as e:
            log.error(f"An unexpected error occurred: {e}", exc_info=True)
            yield 'data: {"error": "Une erreur inattendue est survenue dans le pipe."}\n\n'

        yield "data: [DONE]\n\n"


            