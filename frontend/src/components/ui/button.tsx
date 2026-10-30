import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-50 select-none cursor-pointer leading-none align-middle tracking-normal text-center",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground hover:bg-primary/92 shadow-xs active:translate-y-[0.5px]",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/92 shadow-xs active:translate-y-[0.5px]",
        outline:
          "border border-border bg-card text-foreground hover:bg-muted hover:text-foreground active:translate-y-[0.5px]",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80 active:translate-y-[0.5px]",
        ghost:
          "text-muted-foreground hover:bg-muted hover:text-foreground",
        link:
          "text-primary underline-offset-4 hover:underline p-0 h-auto",
        glass:
          "border border-border/80 bg-card/80 backdrop-blur-xs hover:bg-card active:translate-y-[0.5px]",
      },
      size: {
        default: "h-9 px-4 text-xs",
        sm: "h-8 px-3 text-xs",
        xs: "h-7 px-2.5 text-[11px]",
        lg: "h-10 px-5 text-sm font-medium",
        icon: "h-9 w-9 p-0",
        "icon-sm": "h-7 w-7 p-0",
        "icon-xs": "h-6 w-6 p-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  isLoading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, isLoading, children, disabled, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        suppressHydrationWarning
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin shrink-0" />}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
