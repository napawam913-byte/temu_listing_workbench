# Temu GPT Main Image Automator

Chrome MV3 extension for batching product images through a two-step ChatGPT web workflow:

1. Upload image and ask GPT to plan the Temu US main image edit.
2. Ask GPT to execute the plan and generate the final image.
3. Download the final generated image automatically.

## Install

1. Open Chrome and go to `chrome://extensions`.
2. Enable Developer mode.
3. Click Load unpacked.
4. Select `D:\Desktop\上架\temu-gpt-extension`.

## Use

1. Log in to ChatGPT in Chrome.
2. Click the extension icon to open the Chrome side panel.
3. Click Open GPT once, then keep the side panel open.
4. Choose a folder of `jpg`, `jpeg`, `png`, or `webp` images.
5. Click Start.

The extension opens normal ChatGPT at `https://chatgpt.com/`, not temporary chat, because temporary chats cannot generate images.

The extension processes each image as:

`pending_plan -> planning -> planned -> executing -> downloading -> completed`

Failed items are skipped after one retry and kept in the exported log.

## Notes

- Keep the dashboard tab open while a batch is running.
- The extension saves images under Chrome downloads in `temu-gpt-main-images/`.
- ChatGPT web page changes may require selector maintenance in `contentScript.js`.
