# CS2 Video Plugin

This directory contains the local CS2 video-production integration.

- `third_party/cs-demo-downloader`: Perfect World Demo download and signing support.
- `third_party/cs2-insight-agent`: Demo parsing, clip analysis, recording, and composition backend.

The application resolves these paths through `instconfig/cs2_video_config.json`.
Third-party source code is kept in-tree for local-only operation. Their local credentials,
databases, downloaded demos, exports, caches, and logs are ignored by Git.
