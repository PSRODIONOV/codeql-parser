package branches;

public class OtherDemo {
    private final String tag;

    // Явный super() первым оператором тела - probe_points.ql вставляет
    // датчик входа ФО ПОСЛЕ него (см. explicitCtorCall), а не в начало тела.
    public OtherDemo() {
        super();
        this.tag = "other";
    }

    public String describe() {
        return "OtherDemo:" + tag;
    }
}
