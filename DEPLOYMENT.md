# HAL 9000 Deployment Cheat Sheet

**1. Push changes from Mac:**
```bash
git add .
git commit -m "update"
git push origin main
```

**2. Deploy on Hefner Server:**
```bash
# Connect and deploy in one command:
ssh -t docdoc1@87.99.142.137 './deploy_hal9000.sh'
```
*(If you just need to access the server shell, use: `ssh -t docdoc1@87.99.142.137 'exec bash -l'`)*

**3. Access on iPhone:**
Go to **`https://87.99.142.137:8000/`** 
*(Must use `https://` or the microphone won't work)*
