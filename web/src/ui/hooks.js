// hooks.js: Wiederverwendbare React-Hooks fuer Media-Queries und asynchrone Daten
import React from "react";

const { useState, useEffect, useCallback, useRef } = React;

export function useMedia(query) {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mediaQuery = window.matchMedia(query);
    const handler = () => setMatches(mediaQuery.matches);
    mediaQuery.addEventListener("change", handler);
    return () => mediaQuery.removeEventListener("change", handler);
  }, [query]);

  return matches;
}

export function useAsync(fn, deps = []) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const countRef = useRef(0);

  const execute = useCallback(() => {
    const current = ++countRef.current;
    setLoading(true);
    setError(null);
    return Promise.resolve()
      .then(() => fn())
      .then((result) => {
        if (current === countRef.current) {
          setData(result);
          setLoading(false);
        }
        return result;
      })
      .catch((err) => {
        if (current === countRef.current) {
          setError(err);
          setLoading(false);
        }
        throw err;
      });
  }, deps);

  useEffect(() => {
    execute().catch(() => {});
  }, [execute]);

  return { data, error, loading, reload: execute };
}
