import { Navigate, Route, Routes } from "react-router-dom";

import { getToken } from "./api";
import Chat from "./pages/Chat";
import Library from "./pages/Library";
import Login from "./pages/Login";

/** Only show the page if the user is logged in, otherwise go to the login page. */
function ProtectedRoute({ children }) {
  if (getToken() === null) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

/** The main app with all page routes. */
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Library />
          </ProtectedRoute>
        }
      />
      <Route
        path="/chat"
        element={
          <ProtectedRoute>
            <Chat />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}