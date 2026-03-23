import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../contexts/AuthContext";

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username, password);
      navigate("/");
    } catch (submitError) {
      setError(submitError.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fullscreen-center">
      <form className="glass auth-card" onSubmit={submit}>
        <p className="eyebrow">private access</p>
        <h1>Вход в MediaHub</h1>
        <label>
          Логин
          <input value={username} onChange={(event) => setUsername(event.target.value)} required />
        </label>
        <label>
          Пароль
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>
        {error ? <div className="error-box">{error}</div> : null}
        <button className="primary-button" disabled={busy}>
          {busy ? "Проверяю…" : "Войти"}
        </button>
      </form>
    </div>
  );
}
