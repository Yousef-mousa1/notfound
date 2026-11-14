import { useCallback, useEffect, useRef, useState } from "react";

const serializeDeps = (deps) => {
  try {
    return JSON.stringify(deps);
  } catch {
    return String(deps.length);
  }
};

// Runs an async loader and exposes { data, error, loading, reload }.
//
// State is stored together with the key of the request that produced it, so
// "loading" is derived during render instead of being set synchronously inside
// an effect. The in-flight request is aborted when deps change or on unmount.
export function useApi(loader, deps = []) {
  const key = serializeDeps([...deps]);
  const [result, setResult] = useState({ key: null, data: null, error: null });
  const [nonce, setNonce] = useState(0);
  const requestKey = `${key}::${nonce}`;

  const loaderRef = useRef(loader);

  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    const controller = new AbortController();
    let active = true;

    Promise.resolve()
      .then(() => loaderRef.current({ signal: controller.signal }))
      .then((data) => {
        if (active) setResult({ key: requestKey, data, error: null });
      })
      .catch((error) => {
        if (!active || error?.code === "aborted") return;
        setResult({ key: requestKey, data: null, error });
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [requestKey]);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  const isCurrent = result.key === requestKey;

  return {
    data: isCurrent ? result.data : null,
    error: isCurrent ? result.error : null,
    loading: !isCurrent,
    reload,
  };
}
