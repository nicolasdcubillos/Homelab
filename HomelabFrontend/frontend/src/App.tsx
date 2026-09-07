/**
 * Raíz de la aplicación: proveedores, rutas y guardas de sesión.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { ProveedorAvisos } from "./components/Avisos";
import { Cargando } from "./components/Cargando";
import { Disposicion } from "./components/Disposicion";
import { ApiError } from "./lib/api";
import { useSesion } from "./lib/consultas";
import { ProveedorTema } from "./lib/tema";
import { Actividad } from "./routes/Actividad";
import { Admin } from "./routes/Admin";
import { AdminUsuario } from "./routes/AdminUsuario";
import { Ajustes } from "./routes/Ajustes";
import { CambiarPassword } from "./routes/CambiarPassword";
import { Inicio } from "./routes/Inicio";
import { Login } from "./routes/Login";
import { NoEncontrado } from "./routes/NoEncontrado";
import { Portafolio } from "./routes/Portafolio";
import { Registro } from "./routes/Registro";
import { Trading } from "./routes/Trading";
import { Vigilancias } from "./routes/Vigilancias";

const cliente = new QueryClient({
  defaultOptions: {
    queries: {
      // Una sesión caducada o un permiso denegado no se arreglan repitiendo:
      // reintentar solo tiene sentido ante fallos transitorios.
      retry: (intentos, error) => {
        if (error instanceof ApiError && error.status < 500) return false;
        return intentos < 2;
      },
      staleTime: 15_000,
      refetchOnWindowFocus: true,
    },
    mutations: { retry: false },
  },
});

/** Deja pasar solo a quien tiene sesión; recuerda a dónde quería ir. */
function Privada({
  children,
  soloAdmin = false,
  soloTrading = false,
}: {
  children: React.ReactNode;
  soloAdmin?: boolean;
  soloTrading?: boolean;
}) {
  const { data: sesion, isPending, isError } = useSesion();
  const ubicacion = useLocation();

  if (isPending) return <Cargando />;

  if (isError || !sesion) {
    return <Navigate to="/entrar" replace state={{ destino: ubicacion.pathname }} />;
  }

  // Una contraseña marcada para cambio bloquea el resto de la API, así que la
  // SPA lleva al usuario allí en vez de dejarlo chocar con errores.
  if (sesion.user.must_change_password && ubicacion.pathname !== "/cambiar-password") {
    return <Navigate to="/cambiar-password" replace />;
  }

  if (soloAdmin && sesion.user.role !== "admin") {
    return <Navigate to="/" replace />;
  }

  // El trading no se concede por rol sino por permiso explícito, y la API
  // responde 404 a quien no lo tiene. Redirigir en vez de dejar entrar evita
  // pintar una pantalla entera de errores para explicar «no tienes acceso».
  if (soloTrading && !sesion.user.trading_level) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

/** Las pantallas de acceso no deben verse con la sesión ya abierta. */
function Publica({ children }: { children: React.ReactNode }) {
  const { data: sesion, isPending } = useSesion();

  if (isPending) return <Cargando />;
  if (sesion && !sesion.user.must_change_password) return <Navigate to="/" replace />;
  if (sesion?.user.must_change_password) return <Navigate to="/cambiar-password" replace />;

  return <>{children}</>;
}

function Rutas() {
  return (
    <Routes>
      <Route
        path="/entrar"
        element={
          <Publica>
            <Login />
          </Publica>
        }
      />
      <Route
        path="/registro"
        element={
          <Publica>
            <Registro />
          </Publica>
        }
      />
      <Route
        path="/cambiar-password"
        element={
          <Privada>
            <CambiarPassword />
          </Privada>
        }
      />

      <Route
        element={
          <Privada>
            <Disposicion />
          </Privada>
        }
      >
        <Route path="/" element={<Inicio />} />
        <Route path="/vigilancias" element={<Vigilancias />} />
        <Route path="/portafolio" element={<Portafolio />} />
        <Route
          path="/trading"
          element={
            <Privada soloTrading>
              <Trading />
            </Privada>
          }
        />
        <Route path="/actividad" element={<Actividad />} />
        <Route path="/ajustes" element={<Ajustes />} />
        <Route
          path="/admin"
          element={
            <Privada soloAdmin>
              <Admin />
            </Privada>
          }
        />
        <Route
          path="/admin/usuarios/:id"
          element={
            <Privada soloAdmin>
              <AdminUsuario />
            </Privada>
          }
        />
        <Route path="*" element={<NoEncontrado />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <QueryClientProvider client={cliente}>
      <ProveedorTema>
        <ProveedorAvisos>
          <BrowserRouter>
            <Rutas />
          </BrowserRouter>
        </ProveedorAvisos>
      </ProveedorTema>
    </QueryClientProvider>
  );
}
