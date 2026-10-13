/** Supply only the native methods required for PKCE S256, without replacing existing crypto. */
type NativeCrypto = {
  randomValues: (array: Uint32Array) => Uint32Array;
  sha256: (data: ArrayBuffer | ArrayBufferView) => Promise<ArrayBuffer>;
};
type CryptoTarget = { crypto?: unknown };

export function installPkceCrypto(target: CryptoTarget, native: NativeCrypto): void {
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
