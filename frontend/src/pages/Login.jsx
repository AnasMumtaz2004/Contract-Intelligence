import { useState } from "react";
import { useNavigate } from "react-router-dom";

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
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm rounded-lg bg-white p-6 shadow">
        <h1 className="mb-1 text-xl font-semibold">Contract Intelligence</h1>
        <p className="mb-6 text-sm text-gray-600">
          {isRegisterMode ? "Create an account" : "Log in to your account"}
        </p>

        <label className="mb-1 block text-sm font-medium">Email</label>
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="mb-3 w-full rounded border border-gray-300 px-3 py-2 text-sm"
          required
        />

        <label className="mb-1 block text-sm font-medium">Password</label>
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          className="mb-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
          minLength={8}
          maxLength={72}
          required
        />
        {isRegisterMode && <p className="mb-3 text-xs text-gray-500">At least 8 characters.</p>}

        {error !== "" && <p className="my-3 text-sm text-red-600">{error}</p>}

        <div className="mt-4">
          <Button type="submit" disabled={isLoading}>
            {isRegisterMode ? "Register" : "Log in"}
          </Button>
        </div>

        <button
          type="button"
          onClick={() => setIsRegisterMode(!isRegisterMode)}
          className="mt-4 text-sm text-blue-600 hover:underline"
        >
          {isRegisterMode ? "I already have an account" : "Create a new account"}
        </button>
      </form>
    </div>
  );
}