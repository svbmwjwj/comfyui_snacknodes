# SnackNodes 🍿

> **All nodes in this pack have been retired.** ComfyUI core now ships equivalent nodes.
> Loading an old workflow will show these nodes as missing — replace them as below.

| Retired node | Core replacement |
|---|---|
| Text Box 🍿 (`TextBox`) | **Text (Multiline)** (`PrimitiveStringMultiline`) |
| Image Info 🍿 (`ImageInfo`) | **Get Image Size** (`GetImageSize`) |
| Text Processor 🍿 (`TextProcessor`) | **Concatenate Text** (`StringConcatenate`), **Replace Text** (`StringReplace`), **Preview Any** (`PreviewAny`) |
| Image Scaler 🍿 (`ImageScaler`) | **Scale Image to Total Pixels** (`ImageScaleToTotalPixels`, use `resolution_steps` for alignment), **Resize And Pad Image** (`ResizeAndPadImage`), **Resize Image/Mask** (`ResizeImageMaskNode`) |

## Acknowledgements 🙏

- [ComfyUI-Custom-Scripts](https://github.com/pythongosssss/ComfyUI-Custom-Scripts) by [pythongosssss](https://github.com/pythongosssss), which inspired the original text nodes.
