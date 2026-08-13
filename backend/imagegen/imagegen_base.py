"""Abstract base class for image generation engines."""
from abc import ABC, abstractmethod
from typing import Optional


class ImageGenBase(ABC):
    """Base class that all image generation engines must implement."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        output_dir: str,
        *,
        negative_prompt: str = "",
        resolution: str = "1K",
        aspect_ratio: str = "1:1",
        num_images: int = 1,
        ref_images: Optional[list] = None,
        model: str = "",
        **kwargs,
    ) -> list:
        """
        Generate images from text prompt or reference images.

        Args:
            prompt: Text prompt for image generation
            output_dir: Directory to save generated images
            negative_prompt: Negative prompt to avoid certain features
            resolution: Output resolution - "1K", "2K", or "4K"
            aspect_ratio: Aspect ratio - "16:9", "9:16", "4:3", "3:4", "1:1", etc.
            num_images: Number of images to generate
            ref_images: List of reference image paths (for image-to-image mode)
            model: Model name/ID to use
            **kwargs: Additional engine-specific parameters

        Returns:
            List of generated image file paths
        """
        ...
