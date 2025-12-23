import torch
print(f'PyTorch Version: {torch.__version__}')
print(f'CUDA Available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'CUDA Device: {torch.cuda.get_device_name(0)}')
    print(f'CUDA Version: {torch.version.cuda}')
else:
    print('CUDA Device: N/A (CPU only)')
