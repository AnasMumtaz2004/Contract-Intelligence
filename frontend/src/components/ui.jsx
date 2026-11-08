// Full class names are written out so Tailwind can find them
const BADGE_COLORS = {
  uploaded: "bg-gray-100 text-gray-700",
  parsing: "bg-blue-100 text-blue-800",
  chunking: "bg-blue-100 text-blue-800",
  embedding: "bg-blue-100 text-blue-800",
  ready: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  found: "bg-green-100 text-green-800",
  not_found: "bg-yellow-100 text-yellow-800",
};

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
    <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-300 border-t-blue-600" />
  );
}

/** A popup window with a title, placed over the page. */
export function Modal(props) {
  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-lg bg-white p-6 shadow-lg">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{props.title}</h2>
          <button onClick={props.onClose} className="text-gray-500 hover:text-gray-800">
            ✕
          </button>
        </div>
        {props.children}
      </div>
    </div>
  );
}