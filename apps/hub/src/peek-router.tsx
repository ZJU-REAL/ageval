import {
  createContext,
  useContext,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  NavigationType,
  UNSAFE_LocationContext,
  UNSAFE_NavigationContext,
  UNSAFE_RouteContext,
  UNSAFE_createMemoryHistory,
} from "react-router-dom";

type PeekHistory = {
  canBack: boolean;
  canForward: boolean;
  back: () => void;
  forward: () => void;
};

const PeekHistoryContext = createContext<PeekHistory | null>(null);

export function usePeekHistory(): PeekHistory | null {
  return useContext(PeekHistoryContext);
}

/**
 * In-modal history. React Router 7 forbids a nested <Router>, so this
 * overrides location/navigation context only. Outer Inbox URL stays put.
 */
export function PeekRouter({
  initial,
  children,
}: {
  initial: string;
  children: ReactNode;
}) {
  const historyRef = useRef<ReturnType<typeof UNSAFE_createMemoryHistory> | null>(
    null,
  );
  if (historyRef.current == null) {
    historyRef.current = UNSAFE_createMemoryHistory({
      initialEntries: [initial],
      initialIndex: 0,
      v5Compat: true,
    });
  }
  const history = historyRef.current;
  const [location, setLocation] = useState(history.location);
  const [index, setIndex] = useState(0);
  const [length, setLength] = useState(1);

  useLayoutEffect(() => {
    return history.listen(({ action, location: next }) => {
      setLocation(next);
      const nextIndex = history.index;
      setIndex(nextIndex);
      if (action === NavigationType.Push) setLength(nextIndex + 1);
    });
  }, [history]);

  const navigation = useMemo(
    () => ({
      basename: "/",
      navigator: history,
      static: false,
      future: {},
      useTransitions: false,
    }),
    [history],
  );
  const locationValue = useMemo(
    () => ({ location, navigationType: NavigationType.Push }),
    [location],
  );

  const stack = useMemo<PeekHistory>(
    () => ({
      canBack: index > 0,
      canForward: index < length - 1,
      back: () => {
        if (history.index > 0) history.go(-1);
      },
      forward: () => {
        if (history.index < length - 1) history.go(1);
      },
    }),
    [history, index, length],
  );

  return (
    <PeekHistoryContext.Provider value={stack}>
      <UNSAFE_RouteContext.Provider
        value={{ outlet: null, matches: [], isDataRoute: false }}
      >
        <UNSAFE_NavigationContext.Provider value={navigation}>
          <UNSAFE_LocationContext.Provider value={locationValue}>
            {children}
          </UNSAFE_LocationContext.Provider>
        </UNSAFE_NavigationContext.Provider>
      </UNSAFE_RouteContext.Provider>
    </PeekHistoryContext.Provider>
  );
}
