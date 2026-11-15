import { useEffect, useRef } from "react";

/**
 * Open dialogs, innermost last. Only the top dialog reacts to Escape and Tab,
 * so one Escape press closes one dialog instead of every open one.
 */
const openDialogs: symbol[] = [];

/** True while any dialog using `useModalDialog` is open. */
export function isModalDialogOpen(): boolean {
  return openDialogs.length > 0;
}

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

function focusableIn(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE));
}

/**
 * Modal dialog behaviour for an element rendered while `isOpen` is true:
 * moves focus into the dialog, keeps Tab inside it, closes on Escape when it
 * is the topmost dialog, and returns focus to the opener when it closes.
 *
 * Attach the returned ref to the element with `role="dialog"`, and give that
 * element `tabIndex={-1}` so it can hold focus when it has no controls.
 */
export function useModalDialog<T extends HTMLElement>(isOpen: boolean, onClose: () => void) {
  const dialogRef = useRef<T | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return;
    const id = Symbol("dialog");
    openDialogs.push(id);
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const dialog = dialogRef.current;
    if (dialog && !dialog.contains(document.activeElement)) {
      (focusableIn(dialog)[0] ?? dialog).focus();
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (openDialogs[openDialogs.length - 1] !== id) return;
      const current = dialogRef.current;
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !current) return;
      const items = focusableIn(current);
      if (items.length === 0) {
        event.preventDefault();
        current.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const outside = !current.contains(active);
      if (event.shiftKey && (active === first || active === current || outside)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (active === last || outside)) {
        event.preventDefault();
        first.focus();
      }
    };

    // Global shortcut handlers check isModalDialogOpen() and stand down, so
    // listener order on window does not matter.
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      const index = openDialogs.indexOf(id);
      if (index >= 0) openDialogs.splice(index, 1);
      if (opener?.isConnected) opener.focus();
    };
  }, [isOpen]);

  return dialogRef;
}
