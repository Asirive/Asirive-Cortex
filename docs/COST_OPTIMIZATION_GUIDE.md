# Cost Optimization Guide - Project Cortex v2.0

**Smart API Usage for YIA 2026 Budget**

---

## 💰 Tier Pricing Breakdown

### **Tier 0: Gemini Live API** (Native Audio-to-Audio)
- **Cost**: ~$1.08/hour ($64.80/month full-time)
- **Latency**: <500ms ⚡ (FASTEST)
- **Use Case**: YIA demos, competitions, presentations
- **Budget**: $5-10/month (5-10 demo hours)

### **Tier 1: Gemini TTS** (HTTP, 6-key rotation)
- **Cost**: FREE ✅
- **Latency**: ~1-2s (acceptable for testing)
- **Use Case**: Daily testing, development, debugging
- **Budget**: $0 (unlimited for prototyping)

### **Tier 2: Z.ai GLM-4.6V** (DISABLED)
- **Cost**: ~$5-10 one-time
- **Latency**: ~1-2s
- **Status**: Disabled (redundant with Tier 1 FREE)

---

## 🎯 Smart Usage Strategy

### **Mode 1: "Testing (FREE)"** - DEFAULT ⭐
**When to use**: 
- Daily development
- Feature testing
- Debugging
- Learning the system

**Cost**: $0/month
**API**: Tier 1 (Gemini TTS) only
**Latency**: ~1-2s (acceptable for testing)

### **Mode 2: "Demo Mode (PAID)"** - YIA ONLY
**When to use**:
- YIA 2026 competition
- Important presentations
- Judge demonstrations
- School showcases

**Cost**: ~$1/hour = $0.50 per 30-min demo
**API**: Tier 0 (Live API) only
**Latency**: <500ms ⚡ (your competitive advantage)

### **Mode 3: "Auto (Cascading)"** - SMART FALLBACK
**When to use**:
- Uncertain situations
- Testing fallback system
- Real-world deployment

**Cost**: Variable (starts with Tier 0, falls back to FREE Tier 1)
**Behavior**: Tier 0 → Tier 1 (automatic)

---

## 📊 Monthly Budget Examples

### **Prototype Phase** (Now → YIA 2026)
```
Testing (FREE):     60 hours × $0       = $0
Demo Mode:          5 hours  × $1.08    = $5.40
──────────────────────────────────────────────
Total:                                    $5.40/month ✅
```

### **Competition Month** (YIA 2026)
```
Testing (FREE):     40 hours × $0       = $0
Demo Mode:          20 hours × $1.08    = $21.60
──────────────────────────────────────────────
Total:                                    $21.60/month ✅
```

### **Production Deployment** (Post-YIA)
```
Live Users:         100 hours × $1.08   = $108
Apply for Google AI grants or scholarships 💰
```

---

## 🎮 How to Switch Modes in GUI

**Location**: Top-right dropdown "AI Tier"

**Options**:
1. **"Testing (FREE)"** ← Use this by default
2. **"Demo Mode (PAID)"** ← Switch before demos
3. **"Auto (Cascading)"** ← Smart fallback
4. **"Tier 0 (Live API)"** ← Force fast (paid)
5. **"Tier 1 (Gemini TTS)"** ← Force free

**Default**: Testing (FREE) - saves money

---

## 💡 Pro Tips

### **Tip 1: Switch Before Demo**
```
Before YIA presentation:
1. Open GUI
2. Select "Demo Mode (PAID)"
3. Present to judges (<500ms response)
4. Switch back to "Testing (FREE)" after
```

### **Tip 2: Monitor Usage**
Check Gemini Console: https://ai.google.dev/
- Track Tier 0 usage
- Set budget alerts
- Monitor monthly spend

### **Tip 3: Optimize Queries**
```
More Expensive (Tier 0):
❌ "Tell me about the history of computers" (long response)

Less Expensive:
✅ "What do you see?" (short response)
✅ "Read this label" (focused query)
```

### **Tip 4: Test Smart**
```
Development Flow:
1. Use "Testing (FREE)" for feature development
2. Use "Demo Mode (PAID)" for final validation only
3. Document bugs in FREE mode, fix in FREE mode
4. Only test latency-critical features in PAID mode
```

---

## 🏆 YIA 2026 Budget Recommendation

**Total Budget**: $20-30 for entire competition

**Breakdown**:
- Prototyping (3 months): $5/month × 3 = $15
- Competition Month: $20
- Buffer: $5

**ROI**: 
- Investment: $30
- Potential Scholarship: $1,000+ 🎓
- Gold Medal: Priceless 🏆

---

## 🔄 Fallback Behavior

### **"Testing (FREE)" Mode**:
```
User Query → Tier 1 (Gemini TTS) → Response
              ↓
           Always FREE
```

### **"Demo Mode (PAID)" Mode**:
```
User Query → Tier 0 (Live API) → Response
              ↓
          ~$0.02/query
```

### **"Auto (Cascading)" Mode**:
```
User Query → Tier 0 (Live API) → Success? → Response
              ↓ Quota exceeded
              Tier 1 (Gemini TTS) → Response
              ↓
             FREE fallback
```

---

## ⚠️ Important Notes

1. **Gemini Live API is PAID**: 
   - Not free tier
   - ~$1/hour usage
   - Set budget alerts

2. **Tier 1 is ALWAYS FREE**:
   - 1,500 requests/day per key
   - 6 keys = 9,000 requests/day
   - Unlimited for prototyping

3. **Z.ai Requires Credits**:
   - Currently disabled
   - Coding Plan ≠ API credits
   - Not needed (Tier 1 is free fallback)

4. **Default to FREE**:
   - GUI starts in "Testing (FREE)"
   - Switch to "Demo Mode" only for presentations
   - Save money during development

---

## 📞 Support

**Questions?**
- Check Gemini Pricing: https://ai.google.dev/pricing
- Monitor Usage: https://console.cloud.google.com/
- Budget Alerts: Set in Google Cloud Console

**Pro Tip**: Apply for Google AI Research Credits (up to $500 for student projects)!

---

**Remember**: The **<500ms latency** from Tier 0 is your **competitive advantage** against $4,000 OrCam devices. Use it strategically for demos, save money with FREE tier for testing. 🚀
