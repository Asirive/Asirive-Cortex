# Quick Sync Commands - RPi5 (192.168.0.91)

**Username**: cortex
**IP**: 192.168.0.91

---

## **⚡ Git Bash (Recommended)**

Open Git Bash and run:

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

## **📋 Double-click sync.bat**

Now updated with username **cortex** - just double-click!

---

## **SSH into RPi5**

```bash
# Git Bash / PowerShell / CMD
ssh cortex@192.168.0.91
```

---

## **Run Project on RPi5**

```bash
# Option 1: SSH manually
ssh cortex@192.168.0.91
cd ~/ProjectCortex/rpi5
python main.py

# Option 2: One-liner
ssh cortex@192.168.0.91 "cd ~/ProjectCortex/rpi5 && python main.py"
```

---

## **Sync Specific Files**

```bash
# Sync only rpi5 folder
rsync -avz rpi5/ cortex@192.168.0.91:~/ProjectCortex/rpi5/

# Sync only config
rsync -avz rpi5/config cortex@192.168.0.91:~/ProjectCortex/rpi5/

# Sync specific file
rsync -avz rpi5/main.py cortex@192.168.0.91:~/ProjectCortex/rpi5/
```

---

## **Windows SCP (Backup)**

```cmd
scp -r rpi5 cortex@192.168.0.91:~/ProjectCortex/
```

---

**All scripts updated! Username is now: cortex** ✅
