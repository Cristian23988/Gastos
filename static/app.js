document.addEventListener("DOMContentLoaded", () => {

    const tipoIngreso =
    document.getElementById("tipo_ingreso");

    if (!tipoIngreso) {
        return;
    }

    const campoSalario =
    document.getElementById("campo_salario");

    const campoToques =
    document.getElementById("campo_toques");

    const campoOtro =
    document.getElementById("campo_otro");

    function ocultarTodo(){

        campoSalario.style.display = "none";
        campoToques.style.display = "none";
        campoOtro.style.display = "none";
    }

    ocultarTodo();

    tipoIngreso.addEventListener("change", () => {

        ocultarTodo();

        const option =
        tipoIngreso.options[
            tipoIngreso.selectedIndex
        ];

        const tipo =
        option.dataset.tipo;

        console.log(tipo);

        if(tipo === "salario"){

            campoSalario.style.display = "block";
        }

        else if(tipo === "toques"){

            campoToques.style.display = "block";
        }

        else if(tipo === "otro"){

            campoOtro.style.display = "block";
        }

    });

});