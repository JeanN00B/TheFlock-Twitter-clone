"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bird, Home, Newspaper, UserRound, type LucideIcon } from "lucide-react";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { useSession } from "@/features/auth/session-store";
import type { User } from "@/lib/api/port";

const NAV_ITEMS: { href: string; label: string; icon: LucideIcon }[] = [
  { href: "/", label: "Home", icon: Home },
  { href: "/feed", label: "Feed", icon: Newspaper },
  { href: "/my-profile", label: "My profile", icon: UserRound },
];

function initialsFor(user: User): string {
  const fromName = user.displayName
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("");
  if (fromName) return fromName.toUpperCase();
  return user.username.slice(0, 2).toUpperCase();
}

function NavUser({ user }: { user: User }) {
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton size="lg">
          <Avatar>
            {user.avatarUrl ? (
              <AvatarImage src={user.avatarUrl} alt={user.displayName} />
            ) : null}
            <AvatarFallback>{initialsFor(user)}</AvatarFallback>
          </Avatar>
          <span className="grid flex-1 text-left text-sm leading-tight">
            <span className="truncate font-medium">{user.displayName}</span>
            <span className="truncate text-xs text-muted-foreground">
              @{user.username}
            </span>
          </span>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}

/**
 * Authenticated sidebar chrome for the `(shell)` group: brand header,
 * primary nav with active state, and the signed-in user footer.
 * Session gating lives in the shell layout — this component only reads.
 */
export function AppSidebar() {
  const pathname = usePathname();
  const { session } = useSession();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" render={<Link href="/" />}>
              <span className="flex aspect-square size-8 items-center justify-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
                <Bird />
              </span>
              <span className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-medium">FlockTwitter</span>
              </span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <nav aria-label="Primary">
              <SidebarMenu>
                {NAV_ITEMS.map((item) => (
                  <SidebarMenuItem key={item.href}>
                    <SidebarMenuButton
                      isActive={pathname === item.href}
                      render={<Link href={item.href} />}
                    >
                      <item.icon />
                      <span>{item.label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </nav>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        {session ? <NavUser user={session.user} /> : null}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
