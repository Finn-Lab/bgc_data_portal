declare module "shepherd.js" {
  namespace Shepherd {
    interface StepOptionsAttachTo {
      element?: string | HTMLElement;
      on?: string;
    }

    interface StepOptionsButton {
      text: string;
      action: (this: Tour) => void;
      secondary?: boolean;
    }

    interface StepOptionsScrollTo {
      behavior?: ScrollBehavior;
      block?: ScrollLogicalPosition;
    }

    interface StepOptionsCancelIcon {
      enabled: boolean;
    }

    namespace Step {
      interface StepOptions {
        id?: string;
        text?: string;
        attachTo?: StepOptionsAttachTo;
        beforeShowPromise?: () => Promise<unknown>;
        buttons?: StepOptionsButton[];
        scrollTo?: StepOptionsScrollTo | boolean;
        cancelIcon?: StepOptionsCancelIcon;
        popperOptions?: Record<string, unknown>;
      }
    }

    interface TourOptions {
      useModalOverlay?: boolean;
      defaultStepOptions?: Step.StepOptions;
    }

    class Tour {
      constructor(options?: TourOptions);
      addStep(options: Step.StepOptions): void;
      start(): void;
      next(): void;
      back(): void;
      cancel(): void;
      complete(): void;
      on(event: string, handler: () => void): void;
    }
  }

  export default Shepherd;
}
