import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { useWebSocket } from "@/hooks/useWebSocket";
import { fetchDashboard } from "@/api/dashboard";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

/** Map dashboard card URLs to short nav labels. */
const NAV_LABELS: Record<string, string> = {
  "/chat": "Chat",
  "/documents": "Documents",
  "/inbox": "Inbox",
  "/roles": "Roles",
  "/system": "System",
  "/entities": "Entities",
  "/screens": "Screens",
};

/** URLs that should appear in the top nav (skip dashboard itself). */
const NAV_URLS = new Set(Object.keys(NAV_LABELS));

export function NavBar() {
  const { user, logout } = useAuth();
  const { connected } = useWebSocket();
  const location = useLocation();

  const { data } = useQuery({
    queryKey: ["dashboard"],
    queryFn: fetchDashboard,
  });

  const navItems = (data?.cards ?? []).filter((c) => NAV_URLS.has(c.url));

  const initials =
    user?.display_name
      ?.split(" ")
      .map((n) => n[0])
      .join("")
      .toUpperCase()
      .slice(0, 2) || "?";

  return (
    <header className="sticky top-0 z-50 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex h-14 items-center px-4 gap-4">
        <Link to="/" className="font-semibold text-lg mr-2">
          Gilbert
        </Link>

        <nav className="flex items-center gap-1">
          {navItems.map((card) => (
            <Link key={card.url} to={card.url}>
              <Button
                variant={
                  location.pathname.startsWith(card.url) ? "secondary" : "ghost"
                }
                size="sm"
              >
                {NAV_LABELS[card.url] ?? card.title}
              </Button>
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <div
            className={`h-2 w-2 rounded-full ${connected ? "bg-green-500" : "bg-red-500"}`}
            title={connected ? "Connected" : "Disconnected"}
          />

          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  className="relative h-8 w-8 rounded-full"
                />
              }
            >
              <Avatar className="h-8 w-8">
                <AvatarFallback className="text-xs">{initials}</AvatarFallback>
              </Avatar>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <div className="px-2 py-1.5 text-sm">
                <div className="font-medium">{user?.display_name}</div>
                <div className="text-muted-foreground text-xs">
                  {user?.email}
                </div>
              </div>
              <DropdownMenuItem onClick={logout}>Log out</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}
