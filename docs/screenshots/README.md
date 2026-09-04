# Screenshots

This directory is where dashboard screenshots for the README live. It ships
empty because binary images are not committed to the repository.

To capture your own after starting the stack:

1. Start everything (`make dev`, or the backend and frontend separately).
2. Open <http://localhost:8080>.
3. On the **Simulator** page, press **Start** with mode `NORMAL`.
4. Capture the **Dashboard** — this is the "system healthy" view.
5. Switch the mode to `FAKE_SPEED`, press **Apply mode**, wait ten seconds, and
   capture the Dashboard again — the threat badge turns red and the alert feed
   fills with evidence.
6. Switch to `CAN_FLOOD`, wait ten seconds, and capture **Analytics** — the bus
   load plateau crossing both threshold lines is the clearest single image of
   the system working.

Suggested filenames, referenced from the README:

| File                  | View                                    |
| --------------------- | --------------------------------------- |
| `dashboard.png`       | Dashboard, normal traffic               |
| `dashboard-attack.png`| Dashboard during a Fake Speed attack    |
| `security.png`        | Security page with expanded evidence    |
| `analytics.png`       | Analytics during and after a flood      |
| `simulator.png`       | Simulator controls and vehicle state    |
