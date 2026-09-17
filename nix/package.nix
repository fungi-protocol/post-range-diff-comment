{
  perSystem =
    { pkgs, ... }:
    let
      scripts = pkgs.runCommand "post-range-diff-comment-scripts" { } ''
        mkdir -p "$out"
        cp ${../post-range-diff-comment.sh} "$out/post-range-diff-comment.sh"
        cp ${../render.py} "$out/render.py"
      '';
    in
    {
      packages.default = pkgs.writeShellApplication {
        name = "post-range-diff-comment";
        runtimeInputs = [
          pkgs.gh
          pkgs.git
          pkgs.python3
        ];
        text = ''
          exec ${pkgs.bash}/bin/bash ${scripts}/post-range-diff-comment.sh "$@"
        '';
      };
    };
}
