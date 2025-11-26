# Sound Assets Directory

This directory contains audio assets for the 3D Spatial Audio Navigation System.

## Structure

```
sounds/
├── beacons/          # Navigation beacon sounds
│   ├── ping.wav      # Rhythmic navigation ping
│   ├── success.wav   # Target reached chime
│   └── searching.wav # Searching for target
├── alerts/           # Proximity alert sounds
│   ├── notice.wav    # Soft awareness (>2m)
│   ├── warning.wav   # Attention needed (1-2m)
│   ├── danger.wav    # Caution required (0.5-1m)
│   └── critical.wav  # Immediate action (<0.5m)
├── objects/          # Object-specific sounds
│   ├── person.wav    # Human presence
│   ├── vehicle.wav   # Cars, trucks, buses
│   ├── bicycle.wav   # Cyclist warning
│   ├── furniture.wav # Chairs, tables, etc.
│   ├── door.wav      # Door/passage indicator
│   ├── stairs.wav    # Level change warning
│   ├── animal.wav    # Pets (dog, cat)
│   ├── electronic.wav# Phone, laptop, TV
│   ├── traffic.wav   # Traffic lights, stop signs
│   └── generic.wav   # Default sound
└── feedback/         # System feedback sounds
    ├── start.wav     # System started
    ├── stop.wav      # System stopped
    ├── error.wav     # Error occurred
    └── confirm.wav   # Action confirmed
```

## Sound Design Guidelines

### Beacons
- Use distinct, non-fatiguing tones
- Keep under 500ms per ping
- Vary pitch for distance indication

### Alerts
- Use escalating urgency (pitch, tempo)
- Critical alerts should be unmistakable
- Avoid sounds similar to common alarms

### Objects
- Each class needs a unique audio signature
- Sounds should be recognizable but not annoying
- Consider looping capability (1-2 second loops)

## Recommended Sound Sources

Free sound sources for placeholder/production:
- [Freesound.org](https://freesound.org) (CC licenses)
- [ZapSplat](https://www.zapsplat.com) (Free with attribution)
- [Pixabay](https://pixabay.com/sound-effects/) (Free)

## Technical Requirements

- Format: WAV (uncompressed)
- Sample Rate: 44100 Hz
- Channels: Mono (for 3D positioning)
- Bit Depth: 16-bit
