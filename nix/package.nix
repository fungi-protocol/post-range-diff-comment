{
  perSystem =
    { pkgs, ... }:
    {
      packages.default = pkgs.writeShellApplication {
        name = "post-range-diff-comment";
        runtimeInputs = [
          pkgs.gh
          pkgs.git
          pkgs.python3
        ];
        text = ''
          exec bash ${../post-range-diff-comment.sh} "$@"
        '';
      };
    };
}
