/**
 * Pulls mono mic samples and posts copies to the main thread for PCM encoding.
 * Pass-through to output keeps the graph pulling (same role as the old ScriptProcessor → destination).
 */
class AssemblyAICaptureProcessor extends AudioWorkletProcessor {
  process(inputs, outputs) {
    const input = inputs[0];
    const output = outputs[0];
    if (!input?.length) {
      return true;
    }

    const inCh = input[0];
    if (!inCh?.length) {
      return true;
    }

    const outCh = output?.[0];
    if (outCh && outCh.length === inCh.length) {
      outCh.set(inCh);
    }

    const copy = new Float32Array(inCh.length);
    copy.set(inCh);
    this.port.postMessage(copy.buffer, [copy.buffer]);
    return true;
  }
}

registerProcessor('assemblyai-capture', AssemblyAICaptureProcessor);
