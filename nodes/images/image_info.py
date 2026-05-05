"""Image info node for ComfyUI.

This node provides detailed information about input images, including dimensions,
channels, batch size, and other relevant properties. It's useful for debugging
and understanding the characteristics of images in your workflow.
"""

import torch
import logging
from typing import Dict, Tuple, Any
from ..common.base_node import BaseNode

# Configure logging
logger = logging.getLogger(__name__)

class ImageInfo(BaseNode):
    """A node for retrieving image information.
    
    This node provides detailed information about input images, including dimensions,
    channels, batch size, and other relevant properties.
    """
    
    CATEGORY: str = "SnackNodes"
    RETURN_TYPES: tuple[str, str, str, str] = ("INT", "INT", "INT", "INT")
    RETURN_NAMES: tuple[str, str, str, str] = ("width", "height", "batch_size", "channels")
    FUNCTION: str = "get_image_info"
    
    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Dict[str, Any]]:
        """Define the input types for this node.
        
        Returns:
            Dictionary containing input type definitions.
        """
        return {
            "required": {
                "image": ("IMAGE", {"description": "Input image tensor"}),
            }
        }
    
    def get_image_info(self, image: torch.Tensor) -> Tuple[int, int, int, int]:
        """Get image information including dimensions, batch size and channels.
        
        Args:
            image: Input image tensor in (B,H,W,C) format
            
        Returns:
            Tuple containing width, height, batch size and channels
            
        Raises:
            ValueError: If input tensor is not 4-dimensional or is None
        """
        try:
            if image is None:
                raise ValueError("Input image tensor cannot be None")
                
            if not isinstance(image, torch.Tensor):
                raise ValueError(f"Input must be a torch.Tensor, got {type(image)}")

            if len(image.shape) != 4:
                logger.error(f"Invalid image shape: {image.shape}. Expected 4 dimensions (B,H,W,C).")
                raise ValueError(f"Input tensor must be 4-dimensional (B,H,W,C), got {len(image.shape)}D")
                
            batch_size, height, width, channels = image.shape
            logger.debug(f"Image info retrieved: {width}x{height}, batch={batch_size}, channels={channels}")
            
            return (width, height, batch_size, channels)
            
        except Exception as e:
            logger.error(f"Error retrieving image info: {str(e)}")
            # Return zeros as fallback to prevent workflow crash
            return (0, 0, 0, 0) 