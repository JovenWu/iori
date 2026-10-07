"use client"

import {
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
} from "@/components/ui/sidebar"
import Image from "next/image"

export function SidebarHeaderContent() {
  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          size="lg"
          className="pointer-events-none"
        >
          <div className="flex aspect-square size-8 items-center justify-center shrink-0">
            <Image
              src="/logo.svg"
              alt="Sectors Agent logo"
              width={32}
              height={32}
              className="drop-shadow-[0_2px_5px_rgb(62_198_173/0.45)]"
            />
          </div>
          <div className="grid flex-1 text-left text-sm leading-tight shrink-0 group-data-[collapsible=icon]:hidden">
            <span className="truncate font-semibold tracking-tight text-foreground">Sectors Agent</span>
            <span className="truncate text-xs text-muted-foreground/80">
              IDX market intelligence
            </span>
          </div>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  )
}
