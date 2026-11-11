import { createContext, useCallback, useContext, useState } from "react";


const BADGE_COLORS = {
  uploaded: "bg-gray-100 text-gray-700",
  parsing: "bg-blue-100 text-blue-800",
  scanning: "bg-blue-100 text-blue-800",
  chunking: "bg-blue-100 text-blue-800",
  embedding: "bg-blue-100 text-blue-800",
  ready: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  quarantined: "bg-orange-100 text-orange-800",
  found: "bg-green-100 text-green-800",
  not_found: "bg-yellow-100 text-yellow-800",
  partial: "bg-amber-100 text-amber-800",
  conflicting: "bg-red-100 text-red-800",
};

const TOAST_COLORS = {
  success: "bg-green-600 text-white",
  error: "bg-red-600 text-white",
  info: "bg-gray-800 text-white",
};

// How long a toast stays on the screen
const TOAST_SECONDS = 4;

/** A button with a primary (blue), secondary (gray) or danger (red) look. */
export function Button(props) {
  const variant = props.variant ?? "primary";

  let colors = "bg-blue-600 text-white hover:bg-blue-700";
  if (variant === "secondary") {
    colors = "bg-white text-gray-700 border border-gray-300 hover:bg-gray-100";
  }
  if (variant === "danger") {
    colors = "bg-white text-red-600 border border-red-300 hover:bg-red-50";
  }

  return (
    <button
      type={props.type ?? "button"}
      onClick={props.onClick}
      disabled={props.disabled}
      className={"rounded px-4 py-2 text-sm font-medium disabled:opacity-50 " + colors}
    >
      {props.children}
    </button>
  );
}

/** A small colored label that shows a status. */
export function Badge({ status }) {
  const colors = BADGE_COLORS[status] ?? "bg-gray-100 text-gray-700";
  const text = status.replace("_", " ");
  const label = text.charAt(0).toUpperCase() + text.slice(1);

  return <span className={"rounded-full px-2 py-1 text-xs font-medium " + colors}>{label}</span>;
}

/** A small spinning circle. */
export function Spinner() {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600"
    />
  );
}

/** A spinner with a text, for a page that is still loading. */
export function PageLoading({ text }) {
  return (
    <div className="flex items-center justify-center gap-3 rounded bg-white p-10 text-sm text-gray-500 shadow">
      <Spinner />
      <span>{text ?? "Loading..."}</span>
    </div>
  );
}

/** A friendly message for a page that has nothing to show yet. */
export function EmptyState({ title, text, children }) {
  return (
    <div className="rounded bg-white p-8 text-center shadow">
      <p className="font-medium text-gray-700">{title}</p>
      {text && <p className="mt-1 text-sm text-gray-500">{text}</p>}
      {children && <div className="mt-4 flex justify-center">{children}</div>}
    </div>
  );
}

/** A red box with an error message, and a Try again button if a retry function is given. */
export function ErrorBanner({ message, onRetry }) {
  if (!message) {
    return null;
  }

  return (
    <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-800">
      <span>{message}</span>
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

/** A popup window with a title, placed over the page. */
export function Modal(props) {
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
      <div role="dialog" aria-modal="true" className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-6 shadow-lg">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{props.title}</h2>
          <button onClick={props.onClose} aria-label="Close" className="text-gray-500 hover:text-gray-800">
            ✕
          </button>
        </div>
        {props.children}
      </div>
    </div>
  );
}

const ToastContext = createContext(null);
let nextToastId = 1;

/** Shows small messages in the corner of the screen. Wrap the whole app in it. */
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const showToast = useCallback((message, kind = "info") => {
    const id = nextToastId;
    nextToastId += 1;
    setToasts((oldToasts) => [...oldToasts, { id: id, message: message, kind: kind }]);

    // The toast removes itself after a few seconds
    setTimeout(() => {
      setToasts((oldToasts) => oldToasts.filter((toast) => toast.id !== id));
    }, TOAST_SECONDS * 1000);
  }, []);

  return (
    <ToastContext.Provider value={showToast}>
      {children}
      <div aria-live="polite" className="fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2">
        {toasts.map((toast) => (
          <div key={toast.id} className={"rounded px-4 py-3 text-sm shadow-lg " + TOAST_COLORS[toast.kind]}>
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** Get the function that shows a toast: showToast("Saved", "success"). */
export function useToast() {
  return useContext(ToastContext);
}