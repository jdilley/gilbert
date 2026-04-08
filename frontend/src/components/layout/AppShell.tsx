import { Outlet } from "react-router-dom";
import { NavBar } from "./NavBar";

export function AppShell() {
  return (
    <div className="flex min-h-screen flex-col">
      <NavBar />
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}
