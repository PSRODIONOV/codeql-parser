package branches;

public class Main {
    public static void main(String[] args) {
        BranchDemo bd = new BranchDemo(5);
        System.out.println(bd.ifBranch(3));
        System.out.println(bd.ifBranch(-3));
        System.out.println(bd.forBranch(4));
        System.out.println(bd.whileBranch(3));
        System.out.println(bd.tryBranch(2));
        System.out.println(bd.tryBranch(0));
        System.out.println(bd.helper());
        System.out.println(bd.helper(7));
        System.out.println(bd.helper(-7));
        OtherDemo od = new OtherDemo();
        System.out.println(od.describe());
    }
}
