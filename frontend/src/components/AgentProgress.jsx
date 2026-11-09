import { Spinner } from "./ui";

/** A live list of what the agent has done so far. */
export default function AgentProgress({ steps }) {
  return (
    <div className="max-w-3xl rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm">
      <ul className="space-y-1">
        {steps.map((step, index) => (
          <li key={index} className="flex items-start gap-2 text-gray-600">
            <span className="w-4 text-center text-green-700">✓</span>
            <span>{step}</span>
          </li>
        ))}
        {/* The agent is always busy with the next step */}
        <li className="flex items-center gap-2 text-gray-800">
          <Spinner />
          <span>Working...</span>
        </li>
      </ul>
    </div>
  );
}