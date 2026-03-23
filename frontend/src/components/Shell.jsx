import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../contexts/AuthContext";
import { useTheme } from "../contexts/ThemeContext";

function navItems(isAdmin) {
  return [
    { to: "/", label: "Обзор" },
    { to: "/upload", label: "Загрузка" },
    { to: "/library", label: "Библиотека" },
    { to: "/review", label: "Разметка" },
    { to: "/tags", label: "Теги" },
    { to: "/duplicates", label: "Дубликаты" },
    { to: "/shares", label: "Шаринг" },
    ...(isAdmin ? [{ to: "/users", label: "Юзеры" }, { to: "/settings", label: "Сервер" }] : []),
  ];
}

export default function Shell() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const isAdmin = user?.role === "admin";

  return (
    <div className="app-shell">
      <aside className="sidebar glass">
        <div>
          <p className="eyebrow">private media vault</p>
          <h1>MediaHub</h1>
        </div>
        <nav className="sidebar-nav">
          {navItems(isAdmin).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"}>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <button type="button" className="ghost-button" onClick={toggleTheme}>
            {theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          </button>
          <button
            type="button"
            className="ghost-button"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            Выйти
          </button>
        </div>
      </aside>

      <main className="main-column">
        <header className="topbar glass">
          <div>
            <p className="eyebrow">владелец пространства</p>
            <h2>{user?.displayName}</h2>
          </div>
          <div className="status-pill">{isAdmin ? "admin" : "member"}</div>
        </header>
        <div className="page-wrap">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
