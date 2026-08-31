---
name: Environment Note
description: Hard note about the operating environment
---

# Environment Context

CRITICAL NOTE:
The workspace located at `/Users/c/Desktop/HALnosync` is the **local development environment**. 
The actual production server is located at **`hal.tuning.net`**.

When new features are developed locally, they must be manually deployed/transferred to `hal.tuning.net` for HAL to use them.

The files `token.json` and `credentials.json` MUST be copied from this local `backend/` directory to the `backend/` directory on the `hal.tuning.net` production server. Do not commit these files to Git!

**IMPORTANT FOR DEPLOYMENT:**
When you finish a feature, YOU (the agent) are responsible for committing the changes to Git and pushing them (`git add . && git commit -m "..." && git push`). Do not wait for the user to commit your code.
