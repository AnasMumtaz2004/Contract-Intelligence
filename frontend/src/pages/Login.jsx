import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { loginUser, registerUser } from "../api";
import { Button } from "../components/ui";

/** The login page. It can also create a new account. */
export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isRegisterMode, setIsRegisterMode] = useState(false);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  /** Log in (or register first), then go to the library. */
  async function handleSubmit(event) {
    event.preventDefault();
    setError("");
    setIsLoading(true);

    try {
      if (isRegisterMode) {
        await registerUser(email, password);
      }
      await loginUser(email, password);
      navigate("/");
    } catch (err) {
      setError(err.message);
    }

    setIsLoading(false);
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-10 p-6 md:flex-row md:justify-between md:px-24">
      {/* Left: title + tagline */}
      <div className="w-full max-w-xl">
        <h1 className="mb-3 text-6xl font-bold">CONTRACT INTELLIGENCE</h1>
        <p className="text-lg text-gray-600">
          Ask questions about your contracts and get clear, source-backed answers.
        </p>
      </div>

      {/* Right: form card */}
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-lg border border-gray-500 bg-white p-10 shadow-lg"
      >
        {/* Tabs */}
        <div className="mb-9 flex gap-8 border-b border-gray-400">
          <button
            type="button"
            onClick={() => setIsRegisterMode(false)}
            className={`-mb-px border-b-2 px-2 pb-3 text-sm ${
              !isRegisterMode ? "border-blue-600 font-semibold" : "border-transparent"
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => setIsRegisterMode(true)}
            className={`-mb-px border-b-2 px-2 pb-3 text-sm ${
              isRegisterMode ? "border-blue-600 font-semibold" : "border-transparent"
            }`}
          >
            Create account
          </button>
        </div>

        <label className="mb-2 block text-xs font-semibold uppercase">Email</label>
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@domain.com"
          className="mb-6 w-full border border-gray-500 px-3 py-3 text-sm"
          required
        />

        <label className="mb-2 block text-xs font-semibold uppercase">Password</label>
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mb-1 w-full border border-gray-500 px-3 py-3 text-sm"
          minLength={8}
          maxLength={72}
          required
        />
        {isRegisterMode && <p className="mb-3 text-xs text-gray-500">At least 8 characters.</p>}

        {error !== "" && <p className="my-3 text-sm text-red-600">{error}</p>}

        <div className="mt-7 w-full [&>button]:w-full [&>button]:py-3">
          <Button type="submit" disabled={isLoading}>
            {isRegisterMode ? "Create account" : "Sign in"}
          </Button>
        </div>

        {/* Footer */}
        <div className="mt-9 border-t border-gray-400 pt-5">
         
        </div>
      </form>
    </div>
  );
}