import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/hooks/useAuth";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useWsApi } from "@/hooks/useWsApi";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  MessageSquareIcon,
  FileTextIcon,
  InboxIcon,
  ShieldIcon,
  SlidersHorizontalIcon,
  SettingsIcon,
  DatabaseIcon,
  MonitorIcon,
  ClockIcon,
  PackageIcon,
  MenuIcon,
  type LucideIcon,
} from "lucide-react";

/** Nav item config: label, icon component, and color class. */
interface NavItemConfig {
  label: string;
  icon: LucideIcon;
  color: string;
}

const NAV_CONFIG: Record<string, NavItemConfig> = {
  "/chat": { label: "Chat", icon: MessageSquareIcon, color: "text-blue-500" },
  "/documents": { label: "Documents", icon: FileTextIcon, color: "text-amber-500" },
  "/inbox": { label: "Inbox", icon: InboxIcon, color: "text-green-500" },
  "/roles": { label: "Roles", icon: ShieldIcon, color: "text-purple-500" },
  "/scheduler": { label: "Scheduler", icon: ClockIcon, color: "text-teal-500" },
  "/settings": { label: "Settings", icon: SlidersHorizontalIcon, color: "text-orange-500" },
  "/plugins": { label: "Plugins", icon: PackageIcon, color: "text-indigo-500" },
  "/system": { label: "System", icon: SettingsIcon, color: "text-slate-500" },
  "/entities": { label: "Entities", icon: DatabaseIcon, color: "text-cyan-500" },
  "/screens": { label: "Screens", icon: MonitorIcon, color: "text-rose-500" },
};

/** URLs that should appear in the top nav (skip dashboard itself). */
const NAV_URLS = new Set(Object.keys(NAV_CONFIG));

export function NavBar() {
  const { user, logout } = useAuth();
  const { connected } = useWebSocket();
  const api = useWsApi();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);

  const { data } = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.getDashboard,
    enabled: connected,
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
      <div className="flex h-14 items-center gap-2 px-3 sm:gap-4 sm:px-4">
        {/* Mobile hamburger */}
        <Button
          variant="ghost"
          size="icon-sm"
          className="md:hidden"
          onClick={() => setMobileOpen(true)}
          aria-label="Open navigation"
        >
          <MenuIcon className="size-5" />
        </Button>

        <Link to="/" className="font-semibold text-lg sm:mr-2">
          Gilbert
        </Link>

        {/* Desktop horizontal nav */}
        <nav className="hidden md:flex items-center gap-1 overflow-x-auto">
          {navItems.map((card) => {
            const cfg = NAV_CONFIG[card.url];
            const Icon = cfg?.icon;
            const active = location.pathname.startsWith(card.url);
            return (
              <Link key={card.url} to={card.url} title={cfg?.label ?? card.title}>
                <Button
                  variant={active ? "secondary" : "ghost"}
                  size="sm"
                  className="gap-1.5"
                >
                  {Icon && <Icon className={`h-4 w-4 ${cfg.color}`} />}
                  <span className="hidden lg:inline">{cfg?.label ?? card.title}</span>
                </Button>
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-2 sm:gap-3">
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

      {/* Mobile drawer navigation */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent side="left" className="w-72 p-0">
          <SheetHeader>
            <SheetTitle>Gilbert</SheetTitle>
          </SheetHeader>
          <nav className="flex flex-col px-2 pb-4">
            {navItems.map((card) => {
              const cfg = NAV_CONFIG[card.url];
              const Icon = cfg?.icon;
              const active = location.pathname.startsWith(card.url);
              return (
                <Link
                  key={card.url}
                  to={card.url}
                  onClick={() => setMobileOpen(false)}
                  className={`flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors ${
                    active
                      ? "bg-secondary text-foreground"
                      : "text-foreground/80 hover:bg-accent hover:text-foreground"
                  }`}
                >
                  {Icon && <Icon className={`size-4 ${cfg.color}`} />}
                  <span>{cfg?.label ?? card.title}</span>
                </Link>
              );
            })}
          </nav>
        </SheetContent>
      </Sheet>
    </header>
  );
}
