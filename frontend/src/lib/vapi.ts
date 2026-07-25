// Vapi Web SDK loader + env gating.
//
// The SDK is loaded with a dynamic import() so it never executes during an
// env-less build (SSR/prerender) and stays out of the initial bundle. When
// the NEXT_PUBLIC_VAPI_* vars are absent the call UI is hidden entirely and
// this module is effectively dead code — text chat is unchanged.

/** Minimal surface of the Vapi client we actually use. */
export interface VapiClient {
  on(event: string, handler: (payload?: unknown) => void): void;
  start(
    assistantId: string,
    assistantOverrides?: Record<string, unknown>,
  ): Promise<unknown>;
  stop(): void;
  setMuted(muted: boolean): void;
}

type VapiCtor = new (publicKey: string) => VapiClient;

export function getVapiPublicKey(): string | null {
  return process.env.NEXT_PUBLIC_VAPI_PUBLIC_KEY ?? null;
}

export function getVapiAssistantId(): string | null {
  return process.env.NEXT_PUBLIC_VAPI_ASSISTANT_ID ?? null;
}

/** Both env vars present → the Call button and overlay are rendered. */
export function isVoiceConfigured(): boolean {
  return Boolean(getVapiPublicKey() && getVapiAssistantId());
}

let ctorPromise: Promise<VapiCtor> | null = null;

/**
 * Dynamic loader with a module-level cache. @vapi-ai/web ships CJS with
 * `exports.default = Vapi`, so depending on the bundler's interop the
 * constructor may sit one or two `.default` levels deep — unwrap both.
 */
export function loadVapi(): Promise<VapiCtor> {
  if (!ctorPromise) {
    ctorPromise = import("@vapi-ai/web")
      .then((mod: unknown) => {
        const ns = mod as { default?: unknown };
        const level1 = (ns.default ?? ns) as { default?: unknown };
        const ctor = level1.default ?? level1;
        if (typeof ctor !== "function") {
          throw new Error(
            "Vapi SDK did not resolve to a constructor — import shape changed.",
          );
        }
        return ctor as VapiCtor;
      })
      .catch((err) => {
        // Reset so the next tap can retry instead of caching the failure.
        ctorPromise = null;
        throw err;
      });
  }
  return ctorPromise;
}
