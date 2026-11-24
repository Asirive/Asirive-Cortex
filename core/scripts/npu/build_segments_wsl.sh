set -e
export PATH="$HOME/qairt/venv/bin:$HOME/.local/bin:/usr/bin:/bin"
SDK="$HOME/qairt/qairt/2.42.0.251225"; W="$HOME/qairt/work"; SP=${CORTEX_NPU_WORK:?set to the folder with split/ and calib_raw/}
cd "$SDK" && source bin/envsetup.sh >/dev/null 2>&1
export LD_LIBRARY_PATH="$HOME/qairt/libcxx/root/usr/lib/llvm-18/lib:$HOME/qairt/libcxx/root/usr/lib/x86_64-linux-gnu:$(python -c "import sysconfig;print(sysconfig.get_config_var('LIBDIR'))"):${LD_LIBRARY_PATH:-}"
O="$HOME/qairt/seg"; mkdir -p "$O"; cd "$O"
L="$SDK/lib/x86_64-linux-clang"
for k in 0 2 4 6 8 10 12; do
  [ -f "npu$k.bin" ] && { echo "npu$k: have binary"; continue; }
  t0=$(date +%s)
  python "$(dirname "$SP")/seg_calib.py" "$SP/split" "$SP/calib_raw" $k "$O/calib$k" > calib$k.log 2>&1 || { tail -5 calib$k.log; exit 1; }
  qairt-converter --input_network "$SP/split/npu$k.onnx" --output_path npu$k.dlc > conv$k.log 2>&1 || { tail -15 conv$k.log; exit 1; }
  qairt-quantizer --input_dlc npu$k.dlc --input_list calib$k/input_list.txt --output_dlc npu${k}_q.dlc \
     --weights_bitwidth 8 --act_bitwidth 16 --bias_bitwidth 32 --use_per_channel_quantization > quant$k.log 2>&1 || { grep -E "ERROR" quant$k.log | tail -5; exit 1; }
  rm -rf calib$k npu$k.dlc
  echo "{\"graphs\": [{\"graph_names\": [\"npu$k\"], \"O\": 3}], \"devices\": [{\"soc_model\": 37, \"dsp_arch\": \"v68\"}]}" > ext$k.json
  echo "{\"backend_extensions\": {\"shared_library_path\": \"$L/libQnnHtpNetRunExtensions.so\", \"config_file_path\": \"$O/ext$k.json\"}}" > cfg$k.json
  qnn-context-binary-generator --backend $L/libQnnHtp.so --model $L/libQnnModelDlc.so --dlc_path npu${k}_q.dlc \
     --binary_file npu$k --output_dir . --config_file cfg$k.json > ctx$k.log 2>&1 || { grep -E "ERROR|expected" ctx$k.log | head -6; exit 1; }
  echo "npu$k: OK $(( $(date +%s) - t0 ))s $(ls -la npu$k.bin | awk '{print $5}') bytes; $(head -1 calib$k.log 2>/dev/null)"
done
ls -la *.bin; df -h / | tail -1
