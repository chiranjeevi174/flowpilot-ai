import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium leading-normal transition-colors focus:outline-none focus:ring-1.5 focus:ring-ring select-none whitespace-nowrap",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground shadow-xs",
        secondary:
          "border-border/60 bg-muted/70 text-muted-foreground",
        destructive:
          "border-[#C44949]/25 bg-[#C44949]/10 text-[#C44949] dark:text-[#F87171]",
        success:
          "border-[#16866B]/25 bg-[#16866B]/10 text-[#16866B] dark:text-[#2DD4BF]",
        warning:
          "border-[#B7791F]/25 bg-[#B7791F]/10 text-[#B7791F] dark:text-[#FBBF24]",
        info:
          "border-[#087F72]/25 bg-[#087F72]/10 text-[#087F72] dark:text-[#2DD4BF]",
        purple:
          "border-purple-500/25 bg-purple-500/10 text-purple-700 dark:text-purple-300",
        outline:
          "border-border text-foreground bg-card/50",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
