/** Supply only the native methods required for PKCE S256, without replacing existing crypto. */
type NativeCrypto = {
  randomValues: (array: Uint32Array) => Uint32Array;
  sha256: (data: ArrayBuffer | ArrayBufferView) => Promise<ArrayBuffer>;
};
type CryptoTarget = { crypto?: unknown; TextEncoder?: unknown };

export function installPkceCrypto(target: CryptoTarget, native: NativeCrypto): void {
  if (typeof target.TextEncoder !== 'function') {
    class Utf8Encoder {
      readonly encoding = 'utf-8';
      encode(input = ''): Uint8Array {
        const bytes: number[] = [];
        for (const char of String(input)) {
          let point = char.codePointAt(0)!;
          if (point >= 0xd800 && point <= 0xdfff) point = 0xfffd;
          if (point < 0x80) bytes.push(point);
          else if (point < 0x800) bytes.push(0xc0 | (point >> 6), 0x80 | (point & 63));
          else if (point < 0x10000) bytes.push(0xe0 | (point >> 12), 0x80 | ((point >> 6) & 63), 0x80 | (point & 63));
          else bytes.push(0xf0 | (point >> 18), 0x80 | ((point >> 12) & 63), 0x80 | ((point >> 6) & 63), 0x80 | (point & 63));
        }
        return new Uint8Array(bytes);
      }
    }
    Object.defineProperty(target, 'TextEncoder', { configurable: true, value: Utf8Encoder });
  }
  const crypto = (target.crypto || {}) as {
    getRandomValues?: (array: Uint32Array) => Uint32Array;
    subtle?: { digest?: (algorithm: string | { name: string }, data: ArrayBuffer | ArrayBufferView) => Promise<ArrayBuffer> };
  };
  if (typeof crypto.getRandomValues !== 'function') {
    Object.defineProperty(crypto, 'getRandomValues', { configurable: true, value: native.randomValues });
  }
  if (!crypto.subtle) Object.defineProperty(crypto, 'subtle', { configurable: true, value: {} });
  if (typeof crypto.subtle!.digest !== 'function') {
    Object.defineProperty(crypto.subtle, 'digest', { configurable: true, value: async (algorithm: string | { name: string }, data: ArrayBuffer | ArrayBufferView) => {
      const name = typeof algorithm === 'string' ? algorithm : algorithm.name;
      if (name.toUpperCase() !== 'SHA-256') throw new Error('Algoritmo no compatible con el proveedor PKCE.');
      return native.sha256(data);
    } });
  }
  if (!target.crypto) Object.defineProperty(target, 'crypto', { configurable: true, value: crypto });
}
