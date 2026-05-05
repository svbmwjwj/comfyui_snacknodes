"""ImageScaler node for ComfyUI that provides image scaling and transformation capabilities."""

import torch
import numpy as np
import math
import logging
from PIL import Image
from typing import Dict, Tuple, Optional, Any, List, Union
from ..common.base_node import BaseNode

# Configure logging
logger = logging.getLogger(__name__)

from ...config.constants import (
    PADDING_COLORS,
    INTERPOLATION_METHODS,
    RELATIVE_POSITIONS,
    PIXEL_BUDGETS,
    SCALING_FACTORS
)
from ...utils.image_utils import (
    calculate_dimensions,
    crop_image,
    scale_with_padding
)

# Removed _process_image as it is replaced by batch processing in scale_image

class ImageScaler(BaseNode):
    """A node for scaling and transforming images with various options."""
    
    # Class attributes
    CATEGORY: str = "SnackNodes"
    RETURN_TYPES: tuple[str, str, str] = ("IMAGE", "INT", "INT")
    RETURN_NAMES: tuple[str, str, str] = ("image", "width", "height")
    FUNCTION: str = "scale_image"
    OUTPUT_NODE: bool = True
    
    # Constants
    MIN_REASONABLE_SIZE: int = 32
    
    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Dict[str, Any]]:
        """Define the input types for this node.
        
        Returns:
            Dictionary containing input type definitions
        """
        return {
            "required": {
                "image": ("IMAGE", {"description": "Input image (B,H,W,C format)"}),
                "keep_proportion": ("BOOLEAN", {
                    "default": True,
                    "description": "Maintain aspect ratio"
                }),
                "pixels": (list(PIXEL_BUDGETS.keys()), {
                    "default": "1024px²",
                    "description": "Target pixel count"
                }),
                "scaling_factor": (SCALING_FACTORS, {
                    "default": 64,
                    "description": "Size alignment factor"
                }),
                "relative_position": (RELATIVE_POSITIONS, {
                    "default": "center",
                    "description": "Image position"
                }),
                "supersampling": (list(INTERPOLATION_METHODS.keys()), {
                    "default": "none",
                    "description": "Interpolation method"
                }),
                "padding": ("BOOLEAN", {
                    "default": False,
                    "description": "Use padding"
                }),
                "padding_method": (list(PADDING_COLORS.keys()), {
                    "default": "transparent",
                    "description": "Padding method"
                }),
            },
        }
    
    def scale_image(
        self,
        image: torch.Tensor,
        keep_proportion: bool,
        pixels: str,
        scaling_factor: int,
        relative_position: str,
        supersampling: str,
        padding: bool,
        padding_method: str
    ) -> Tuple[torch.Tensor, int, int]:
        """Scale and transform image according to specified logic.
        
        Args:
            image: Input image tensor (B,H,W,C)
            keep_proportion: Whether to maintain aspect ratio
            pixels: Target pixel count
            scaling_factor: Size alignment factor
            relative_position: Image position
            supersampling: Interpolation method
            padding: Whether to use padding
            padding_method: Padding method
            
        Returns:
            Tuple of (output image, width, height)
            
        Raises:
            ValueError: If input parameters are invalid
            Exception: If an error occurs during image processing
        """
        try:
            # Validate input
            if len(image.shape) != 4:
                raise ValueError("Input tensor must be 4-dimensional (B,H,W,C)")
                
            # Get pixel budget
            pixel_budget = PIXEL_BUDGETS.get(pixels)
            if not pixel_budget:
                raise ValueError(f"Invalid pixel budget: {pixels}")
            
            # Extract image info
            batch_size, height, width, channels = image.shape
            
            # Calculate dimensions using utility function
            new_width, new_height = calculate_dimensions(
                width=width,
                height=height,
                max_pixels=pixel_budget,
                scaling_factor=scaling_factor,
                keep_proportion=keep_proportion,
                min_size=self.MIN_REASONABLE_SIZE
            )
            
            # Log results
            logger.debug(f"Scaling batch of {batch_size} to {new_width}x{new_height}")
            
            # Process image batch
            interp_method = INTERPOLATION_METHODS.get(supersampling, Image.NEAREST)
            pad_color = PADDING_COLORS.get(padding_method, (0, 0, 0, 0))
            
            processed_images = []
            for i in range(batch_size):
                # Convert tensor to PIL image
                img_data = (image[i].cpu().numpy() * 255).astype(np.uint8)
                img = Image.fromarray(img_data, 'RGBA' if channels == 4 else 'RGB')
                
                # If transparent padding is requested, ensure we have an alpha channel
                if padding and padding_method == "transparent" and img.mode != "RGBA":
                    img = img.convert("RGBA")
                
                # Resize image
                if padding:
                    img_resized = scale_with_padding(
                        image=img,
                        target_width=new_width,
                        target_height=new_height,
                        position=relative_position,
                        interpolation=interp_method,
                        padding_color=pad_color,
                        min_size=self.MIN_REASONABLE_SIZE
                    )
                else:
                    img_resized = img.resize((new_width, new_height), interp_method)
                
                # Convert back to numpy array and normalize
                img_array = np.array(img_resized).astype(np.float32) / 255.0
                processed_images.append(img_array)
            
            # Combine processed images into a single tensor
            # All images in batch must have same dimensions and channel count
            output = torch.from_numpy(np.stack(processed_images))
            
            return (output, new_width, new_height)
            
        except Exception as e:
            logger.error(f"Error scaling image: {str(e)}")
            raise 
