{
  perSystem =
    { config, pkgs, ... }:
    {
      devShells.default = pkgs.mkShellNoCC {
        packages = [
          pkgs.actionlint
          pkgs.gh
          pkgs.python3
          config.treefmt.build.wrapper
        ];
      };
    };
}
