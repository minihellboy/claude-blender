# SPDX-License-Identifier: MIT
"""
ComfyUI Bridge for local image generation.

Connects to a locally running ComfyUI instance to generate images.
ComfyUI supports Stable Diffusion, SDXL, Flux, and many other models.

Requirements:
    - ComfyUI running locally (default: http://127.0.0.1:8188)
    - Models downloaded to ComfyUI's models folder
"""

import json
import os
import time
import tempfile
import urllib.request
import urllib.error
from typing import Any, Dict, Optional, List
from .base import BaseLocalService, TextureOutputMixin, AIServiceError


class ComfyUIBridge(BaseLocalService, TextureOutputMixin):
    """
    Bridge to local ComfyUI instance for image generation.

    ComfyUI is a powerful node-based UI for Stable Diffusion and other models.
    This bridge allows executing workflows and retrieving generated images.
    """

    # Default workflow for text-to-image
    DEFAULT_WORKFLOW = {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "cfg": 7,
                "denoise": 1,
                "latent_image": ["5", 0],
                "model": ["4", 0],
                "negative": ["7", 0],
                "positive": ["6", 0],
                "sampler_name": "euler",
                "scheduler": "normal",
                "seed": 0,
                "steps": 20
            }
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": "sd_xl_base_1.0.safetensors"
            }
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "batch_size": 1,
                "height": 1024,
                "width": 1024
            }
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": "a beautiful landscape"
            }
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "clip": ["4", 1],
                "text": "ugly, blurry, low quality"
            }
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            }
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "ComfyUI",
                "images": ["8", 0]
            }
        }
    }

    def __init__(self, host: str = "127.0.0.1", port: int = 8188):
        super().__init__()
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"

    @property
    def service_name(self) -> str:
        return "comfyui"

    @property
    def required_packages(self) -> list:
        return []  # No special packages needed, just HTTP

    def is_available(self) -> bool:
        """Check if ComfyUI is running."""
        try:
            req = urllib.request.Request(f"{self.base_url}/system_stats")
            with urllib.request.urlopen(req, timeout=2) as response:
                return response.status == 200
        except:
            return False

    def load_model(self) -> bool:
        """ComfyUI manages its own models."""
        return self.is_available()

    def get_available_models(self) -> Dict[str, List[str]]:
        """Get list of available models in ComfyUI."""
        try:
            req = urllib.request.Request(f"{self.base_url}/object_info")
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())

            models = {}

            # Get checkpoint models
            if "CheckpointLoaderSimple" in data:
                ckpt_info = data["CheckpointLoaderSimple"]["input"]["required"].get("ckpt_name", [[]])
                models["checkpoints"] = ckpt_info[0] if ckpt_info else []

            # Get LoRA models
            if "LoraLoader" in data:
                lora_info = data["LoraLoader"]["input"]["required"].get("lora_name", [[]])
                models["loras"] = lora_info[0] if lora_info else []

            # Get VAE models
            if "VAELoader" in data:
                vae_info = data["VAELoader"]["input"]["required"].get("vae_name", [[]])
                models["vaes"] = vae_info[0] if vae_info else []

            return models
        except Exception as e:
            return {"error": str(e)}

    def _queue_prompt(self, workflow: Dict) -> str:
        """Queue a workflow for execution."""
        data = json.dumps({"prompt": workflow}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/prompt",
            data=data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode())
            return result.get("prompt_id")

    def _get_history(self, prompt_id: str) -> Dict:
        """Get execution history for a prompt."""
        req = urllib.request.Request(f"{self.base_url}/history/{prompt_id}")
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())

    def _wait_for_completion(
        self,
        prompt_id: str,
        timeout: float = 300.0,
        poll_interval: float = 1.0
    ) -> Dict:
        """Wait for a prompt to complete."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            history = self._get_history(prompt_id)
            if prompt_id in history:
                return history[prompt_id]
            time.sleep(poll_interval)

        raise AIServiceError(f"Timeout waiting for prompt {prompt_id}")

    def _download_image(self, filename: str, subfolder: str = "") -> str:
        """Download a generated image from ComfyUI."""
        params = f"filename={filename}"
        if subfolder:
            params += f"&subfolder={subfolder}"

        req = urllib.request.Request(f"{self.base_url}/view?{params}")
        with urllib.request.urlopen(req, timeout=30) as response:
            # Save to temp file
            filepath = os.path.join(self._temp_dir, filename)
            with open(filepath, "wb") as f:
                f.write(response.read())
            return filepath

    def generate(
        self,
        prompt: str,
        negative_prompt: str = "ugly, blurry, low quality",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg: float = 7.0,
        seed: Optional[int] = None,
        checkpoint: Optional[str] = None,
        sampler: str = "euler",
        scheduler: str = "normal",
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Generate an image using ComfyUI.

        Args:
            prompt: Text description of the image
            negative_prompt: What to avoid
            width: Image width
            height: Image height
            steps: Number of sampling steps
            cfg: CFG scale
            seed: Random seed (None for random)
            checkpoint: Model checkpoint name (None for default)
            sampler: Sampler name (euler, dpmpp_2m, etc.)
            scheduler: Scheduler (normal, karras, etc.)
            timeout: Maximum wait time

        Returns:
            Dict with generated image paths
        """
        if not self.is_available():
            return {
                "success": False,
                "error": f"ComfyUI not running at {self.base_url}. Start ComfyUI first."
            }

        # Build workflow
        workflow = json.loads(json.dumps(self.DEFAULT_WORKFLOW))

        # Set parameters
        workflow["6"]["inputs"]["text"] = prompt
        workflow["7"]["inputs"]["text"] = negative_prompt
        workflow["5"]["inputs"]["width"] = width
        workflow["5"]["inputs"]["height"] = height
        workflow["3"]["inputs"]["steps"] = steps
        workflow["3"]["inputs"]["cfg"] = cfg
        workflow["3"]["inputs"]["sampler_name"] = sampler
        workflow["3"]["inputs"]["scheduler"] = scheduler

        if seed is not None:
            workflow["3"]["inputs"]["seed"] = seed
        else:
            import random
            workflow["3"]["inputs"]["seed"] = random.randint(0, 2**32 - 1)

        if checkpoint:
            workflow["4"]["inputs"]["ckpt_name"] = checkpoint

        try:
            # Queue the prompt
            prompt_id = self._queue_prompt(workflow)

            # Wait for completion
            result = self._wait_for_completion(prompt_id, timeout)

            # Get output images
            images = []
            outputs = result.get("outputs", {})
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for img_info in node_output["images"]:
                        filepath = self._download_image(
                            img_info["filename"],
                            img_info.get("subfolder", "")
                        )
                        images.append(filepath)

            return {
                "success": True,
                "images": images,
                "prompt": prompt,
                "seed": workflow["3"]["inputs"]["seed"]
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def execute_workflow(
        self,
        workflow: Dict,
        timeout: float = 300.0
    ) -> Dict[str, Any]:
        """
        Execute a custom ComfyUI workflow.

        Args:
            workflow: ComfyUI workflow JSON
            timeout: Maximum wait time

        Returns:
            Dict with results
        """
        if not self.is_available():
            return {
                "success": False,
                "error": f"ComfyUI not running at {self.base_url}"
            }

        try:
            prompt_id = self._queue_prompt(workflow)
            result = self._wait_for_completion(prompt_id, timeout)

            images = []
            outputs = result.get("outputs", {})
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for img_info in node_output["images"]:
                        filepath = self._download_image(
                            img_info["filename"],
                            img_info.get("subfolder", "")
                        )
                        images.append(filepath)

            return {
                "success": True,
                "images": images,
                "outputs": outputs
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Convenience function
def get_comfyui(host: str = "127.0.0.1", port: int = 8188) -> ComfyUIBridge:
    """Get a ComfyUI bridge instance."""
    return ComfyUIBridge(host, port)
