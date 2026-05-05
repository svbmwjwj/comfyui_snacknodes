"""Text Box node for ComfyUI."""

import logging
from typing import Dict, Tuple, Any
from ..common.base_node import BaseNode

# 配置日志
logger = logging.getLogger(__name__)

class TextBox(BaseNode):
    """A node for handling multiline text input.
    
    This node provides a simple interface for text input with validation
    and error handling capabilities.
    """
    
    CATEGORY: str = "SnackNodes"
    RETURN_TYPES: tuple[str] = ("STRING",)
    RETURN_NAMES: tuple[str] = ("text",)
    FUNCTION: str = "get_text"
    
    @classmethod
    def INPUT_TYPES(cls) -> Dict[str, Dict[str, Any]]:
        """Define the input types for this node.
        
        Returns:
            Dictionary containing input type definitions.
        """
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "placeholder": "Enter your text here..."
                }),
            }
        }
    
    def get_text(self, text: str) -> Tuple[str]:
        """Get the input text with validation.
        
        Args:
            text: The input text
            
        Returns:
            Tuple containing the validated text
            
        Raises:
            ValueError: If text validation fails
        """
        try:
            # Validate input
            if text is None:
                logger.warning("Received None for text input, using empty string")
                return ("",)
                
            # Ensure it's a string
            text = str(text)
                
            # Log debug info
            logger.debug(f"Processing text input: {text[:50]}...")
            
            # Return the text
            return (text,)
            
        except Exception as e:
            logger.error(f"Error processing text: {str(e)}")
            # Return empty string on error
            return ("",) 