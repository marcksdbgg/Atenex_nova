/* Health check hook */
import { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';

export function useHealth() {
  const [connected, setConnected] = useState(false);
  const [version, setVersion] = useState('');
  const [checking, setChecking] = useState(true);

  const check = useCallback(async () => {
    try {
      const res = await api.health();
      setConnected(res.status === 'ok');
      setVersion(res.version);
    } catch {
      setConnected(false);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    check();
    const interval = setInterval(check, 15000);
    return () => clearInterval(interval);
  }, [check]);

  return { connected, version, checking };
}
