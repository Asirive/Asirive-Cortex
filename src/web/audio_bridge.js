/**
 * Project-Cortex Audio Bridge
 * Handles client-side audio recording and device management for NiceGUI.
 */

window.audioRecorder = {
    mediaRecorder: null,
    audioChunks: [],
    stream: null,

    /**
     * Start recording audio from the selected device.
     * @param {string} deviceId - The ID of the audio input device (optional).
     */
    start: async function(deviceId) {
        try {
            const constraints = {
                audio: deviceId ? { deviceId: { exact: deviceId } } : true
            };
            
            this.stream = await navigator.mediaDevices.getUserMedia(constraints);
            this.mediaRecorder = new MediaRecorder(this.stream);
            this.audioChunks = [];

            this.mediaRecorder.ondataavailable = event => {
                this.audioChunks.push(event.data);
            };

            this.mediaRecorder.start();
            console.log("🎤 Recording started");
            return true;
        } catch (err) {
            console.error("❌ Error starting recording:", err);
            return false;
        }
    },

    /**
     * Stop recording and return the audio data as a Base64 string.
     * @returns {Promise<string>} Base64 encoded WAV/WebM audio data.
     */
    stop: function() {
        return new Promise((resolve, reject) => {
            if (!this.mediaRecorder) {
                resolve(null);
                return;
            }

            this.mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(this.audioChunks, { type: 'audio/wav' });
                const reader = new FileReader();
                
                reader.readAsDataURL(audioBlob);
                reader.onloadend = () => {
                    const base64String = reader.result.split(',')[1];
                    resolve(base64String);
                    
                    // Cleanup
                    this.stream.getTracks().forEach(track => track.stop());
                    this.mediaRecorder = null;
                    this.stream = null;
                    console.log("🛑 Recording stopped");
                };
            };

            this.mediaRecorder.stop();
        });
    },

    /**
     * Get a list of available audio input devices.
     * @returns {Promise<Array>} List of devices {id, label}.
     */
    getDevices: async function() {
        try {
            // Request permission first to get labels
            await navigator.mediaDevices.getUserMedia({ audio: true });
            
            const devices = await navigator.mediaDevices.enumerateDevices();
            return devices
                .filter(d => d.kind === 'audioinput')
                .map(d => ({
                    id: d.deviceId,
                    label: d.label || `Microphone ${d.deviceId.slice(0, 5)}`
                }));
        } catch (err) {
            console.error("❌ Error getting devices:", err);
            return [];
        }
    }
};