# Quick Start: Sync Files to RPi5

**Your RPi5 IP**: `192.168.0.91`

## **Method 1: One-line sync (Fastest)**

**On Windows (PowerShell or CMD)**:
```powershell
# Navigate to project directory
cd C:\Users\Haziq\Documents\ProjectCortex

# Sync files (one command)
rsync -avz --progress --exclude=__pycache__/ --exclude=*.pyc --exclude=.git/ --exclude=*.db --exclude=laptop/ --exclude=tests/ --exclude=docs/ --exclude=examples/ ./ cortex@192.168.0.91:~/ProjectCortex/
```

**On Windows (Git Bash)**:
```bash
cd /c/Users/Haziq/Documents/ProjectCortex

rsync -avz --progress \
  --exclude=__pycache__/ \
  --exclude=*.pyc \
  --exclude=.git/ \
  --exclude=*.db \
  --exclude=laptop/ \
  --exclude=tests/ \
  --exclude=docs/ \
  --exclude=examples/ \
  ./ cortex@192.168.0.91:~/ProjectCortex/
```

---

## **Method 2: Use the PowerShell Script**

1. **Edit the script** to add your IP:
   ```powershell
   # Open: sync_to_rpi.ps1
   # Change line 7: $RPI_HOST = "192.168.0.91"
   ```

2. **Run the script**:
   ```powershell
   cd C:\Users\Haziq\Documents\ProjectCortex
   .\sync_to_rpi.ps1
   ```

---

## **Method 3: Manual SCP (If rsync not available)**

```powershell
# On Windows (PowerShell)
scp -r rpi5 cortex@192.168.0.91:~/ProjectCortex/
scp -r supabase cortex@192.168.0.91:~/ProjectCortex/
scp rpi5/config cortex@192.168.0.91:~/ProjectCortex/
```

---

## **After Sync: Run on RPi5**

```bash
# SSH into RPi5
ssh cortex@192.168.0.91

# Navigate to project
cd ~/ProjectCortex/rpi5

# Run main system
python main.py
```

---

## **Setup SSH Key (Optional - Skip Password)**

```powershell
# On Windows (PowerShell)
# Generate SSH key (if you don't have one)
ssh-keygen -t rsa -b 4096

# Copy key to RPi5
cat ~/.ssh/id_rsa.pub | ssh cortex@192.168.0.91 "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

Now you can sync without entering password! 🚀

---

## **Troubleshooting**

### **"rsync not found"**
- Install Git for Windows: https://git-scm.com/download/win
- Or use WSL: `wsl --install -d Ubuntu`

### **"Connection refused"**
- Check RPi5 is on: `ping 192.168.0.91`
- Check SSH enabled on RPi5:
  ```bash
  # On RPi5
  sudo systemctl enable ssh
  sudo systemctl start ssh
  ```

### **"Permission denied"**
- Make sure you're using the correct username (usually `pi`)
- Check password: `ssh pi@192.168.0.91`

---

## **Quick Reference Commands**

```powershell
# Sync everything
rsync -avz --exclude=laptop/ --exclude=tests/ ./ cortex@192.168.0.91:~/ProjectCortex/

# Sync only rpi5/ folder
rsync -avz rpi5/ cortex@192.168.0.91:~/ProjectCortex/rpi5/

# Sync only config files
rsync -avz rpi5/config cortex@192.168.0.91:~/ProjectCortex/rpi5/

# SSH into RPi5
ssh cortex@192.168.0.91

# Run main.py on RPi5
ssh cortex@192.168.0.91 "cd ~/ProjectCortex/rpi5 && python main.py"
```

---

**Your RPi5 is ready! IP: 192.168.0.91** 🎉
