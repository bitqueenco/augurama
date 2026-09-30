# Augurama · Google Antigravity Plugin
**Corgi-Verse Software · Version 1.0.0**

Autonomous video directing and multimodal storyboard orchestration engine powered by fal.ai.
Supports MiniMax H3 Max, Alibaba Wan 3.0, Kuaishou Kling V3 Turbo, and ByteDance Seedance 2.0/2.5.

## Installation

### Method 1: Antigravity CLI / Plugin Manager
```sh
agy plugin install /path/to/augurama/releases/antigravity
agy plugin list
```

### Method 2: Global Configuration Directory
Copy or link the package directory into your global plugins folder:
```sh
mkdir -p ~/.gemini/config/plugins/augurama
cp -R dist/antigravity-package/* ~/.gemini/config/plugins/augurama/
```

### Method 3: Workspace Directory
Place under `.agents/plugins/augurama` within your project workspace.

## Setup & Running the Service

1. **Start the Augurama Backend**:
```sh
uv run augurama serve --host 127.0.0.1 --port 8765
```

2. **Configure Provider Key**:
In the Augurama desk at `http://127.0.0.1:8765/#account`, enter your `FAL_KEY`. Alternatively, set `FAL_KEY` in your environment.

3. **Direct Videos in Chat**:
Use the `/direct-video` skill:
> "Prepare a 10-second cinematic video with MiniMax H3 Max Turbo showing an epic corgi stampede. Show me the contract before generating."
