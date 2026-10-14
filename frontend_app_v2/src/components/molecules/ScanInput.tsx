import { useEffect, useRef, useState } from 'react';
import { ScanLine } from 'lucide-react';
import { Input } from '@/components/atoms/Input';
import { haptic, playBeep } from '@/lib/feedback';
import { cn } from '@/lib/cn';

/**
 * ScanInput - input scanner QR/barcode untuk HP & scanner gun.
 *
 * - auto-focus saat mount (`autoFocus` default true);
 * - debounce 500 ms supaya scanner gun yang mengetik cepat tidak memicu berkali-kali;
 * - setelah kode dikirim: `playBeep('success')` + `haptic('success')` + input dibersihkan;
 * - tekan Enter juga langsung mengirim (scanner gun biasanya mengirim CR).
 */

const SCAN_DEBOUNCE_MS = 500;

interface ScanInputProps {
  onScan: (code: string) => void;
  placeholder?: string;
  autoFocus?: boolean;
  label?: string;
  className?: string;
}

export function ScanInput({
  onScan,
  placeholder = 'Scan QR / barcode bundle',
  autoFocus = true,
  label = 'Scan kode bundle',
  className,
}: ScanInputProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const timerRef = useRef<number | null>(null);
  const [value, setValue] = useState('');

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, []);

  function clearTimer(): void {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }

  function commit(raw: string): void {
    const code = raw.trim();
    if (code.length === 0) return;

    onScan(code);
    playBeep('success');
    haptic('success');
    setValue('');
  }

  function handleChange(raw: string): void {
    setValue(raw);
    clearTimer();

    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      commit(raw);
    }, SCAN_DEBOUNCE_MS);
  }

  return (
    <form
      className={cn('w-full', className)}
      onSubmit={(event) => {
        event.preventDefault();
        clearTimer();
        commit(value);
      }}
    >
      <Input
        ref={inputRef}
        label={label}
        icon={ScanLine}
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        enterKeyHint="done"
        onChange={(event) => handleChange(event.target.value)}
      />
    </form>
  );
}
